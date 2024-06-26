import torch.nn as nn
import torch
import torch.nn.functional as F
from thop import profile
from thop import clever_format
from torchsummary import summary

import numpy as np


from pointnet2_ops import pointnet2_utils

def knn(x, k):
    inner = -2*torch.matmul(x.transpose(2, 1), x)
    xx = torch.sum(x**2, dim=1, keepdim=True)
    pairwise_distance = -xx - inner - xx.transpose(2, 1)
 
    idx = pairwise_distance.topk(k=k, dim=-1)[1]   # (batch_size, num_points, k)
    return idx

def transformer_neighbors(x, feature, k=20, idx=None):
    '''
        input: x, [B,3,N]
               feature, [B,C,N]
        output: neighbor_x, [B,6,N,K]
                neighbor_feat, [B,2C,N,k]
    '''
    batch_size = x.size(0)
    num_points = x.size(2)
    x = x.view(batch_size, -1, num_points)
    if idx is None:
        idx = knn(x, k=k)   # (batch_size, num_points, k)
    device = torch.device('cuda')

    idx_base = torch.arange(0, batch_size, device=device).view(-1, 1, 1)*num_points
    idx_base = idx_base.type(torch.cuda.LongTensor)
    idx = idx.type(torch.cuda.LongTensor)
    idx = idx + idx_base
    idx = idx.view(-1)
 
    _, num_dims, _ = x.size()

    x = x.transpose(2, 1).contiguous()   # (batch_size, num_points, num_dims)  -> (batch_size*num_points, num_dims) #   batch_size * num_points * k + range(0, batch_size*num_points)
    neighbor_x = x.view(batch_size*num_points, -1)[idx, :]
    neighbor_x = neighbor_x.view(batch_size, num_points, k, num_dims) 
    x = x.view(batch_size, num_points, 1, num_dims).repeat(1, 1, k, 1)

    position_vector = (x - neighbor_x).permute(0, 3, 1, 2).contiguous() # B,3,N,k

    _, num_dims, _ = feature.size()

    feature = feature.transpose(2, 1).contiguous()   # (batch_size, num_points, num_dims)  -> (batch_size*num_points, num_dims) #   batch_size * num_points * k + range(0, batch_size*num_points)
    neighbor_feat = feature.view(batch_size*num_points, -1)[idx, :]
    neighbor_feat = neighbor_feat.view(batch_size, num_points, k, num_dims) 
    neighbor_feat = neighbor_feat.permute(0, 3, 1, 2).contiguous() # B,C,N,k
  
    return position_vector, neighbor_feat

class Point_Transformer(nn.Module):
    def __init__(self, input_features_dim):
        super(Point_Transformer, self).__init__()

        self.conv_theta1 = nn.Conv2d(3, input_features_dim, 1)
        self.conv_theta2 = nn.Conv2d(input_features_dim, input_features_dim, 1)
        self.bn_conv_theta = nn.BatchNorm2d(input_features_dim)

        self.conv_phi = nn.Conv2d(input_features_dim, input_features_dim, 1)
        self.conv_psi = nn.Conv2d(input_features_dim, input_features_dim, 1)
        self.conv_alpha = nn.Conv2d(input_features_dim, input_features_dim, 1)

        self.conv_gamma1 = nn.Conv2d(input_features_dim, input_features_dim, 1)
        self.conv_gamma2 = nn.Conv2d(input_features_dim, input_features_dim, 1)
        self.bn_conv_gamma = nn.BatchNorm2d(input_features_dim)

    def forward(self, xyz, features, k):

        position_vector, x_j = transformer_neighbors(xyz, features, k=k)

        delta = F.relu(self.bn_conv_theta(self.conv_theta2(self.conv_theta1(position_vector)))) # B,C,N,k
        # corrections for x_i
        x_i = torch.unsqueeze(features, dim=-1).repeat(1, 1, 1, k) # B,C,N,k

        linear_x_i = self.conv_phi(x_i) # B,C,N,k

        linear_x_j = self.conv_psi(x_j) # B,C,N,k

        relation_x = linear_x_i - linear_x_j + delta # B,C,N,k
        relation_x = F.relu(self.bn_conv_gamma(self.conv_gamma2(self.conv_gamma1(relation_x)))) # B,C,N,k

        weights = F.softmax(relation_x, dim=-1) # B,C,N,k
        features = self.conv_alpha(x_j) + delta # B,C,N,k

        f_out = weights * features # B,C,N,k
        f_out = torch.sum(f_out, dim=-1) # B,C,N

        return f_out

def get_graph_feature(x, k, idx=None):#B, C, N----B, 2*C, N, k
    batch_size = x.size(0)
    num_points = x.size(2)
    x = x.view(batch_size, -1, num_points)
    if idx is None:
        idx = knn(x, k=k)   # (batch_size, num_points, k)
    device = torch.device('cpu')

    idx_base = torch.arange(0, batch_size, device=device).view(-1, 1, 1)*num_points

    idx = (idx + idx_base)

    idx = idx.view(-1)
 
    _, num_dims, _ = x.size()

    x = x.transpose(2, 1).contiguous()   # (batch_size, num_points, num_dims)  -> (batch_size*num_points, num_dims) #   batch_size * num_points * k + range(0, batch_size*num_points)
    feature = x.view(batch_size*num_points, -1)[idx, :]
    feature = feature.view(batch_size, num_points, k, num_dims) 
    x = x.view(batch_size, num_points, 1, num_dims).repeat(1, 1, k, 1)
    
    feature = torch.cat((feature-x, x), dim=3).permute(0, 3, 1, 2).contiguous()
    
  
    return feature

def geometric_point_descriptor(x, k=3, idx=None):
    # x: B,3,N
    batch_size = x.size(0)
    num_points = x.size(2)
    org_x = x
    x = x.view(batch_size, -1, num_points)
    if idx is None:
        idx = knn(x, k=k)  # (batch_size, num_points, k)
    device = torch.device('cuda')

    idx_base = torch.arange(0, batch_size, device=device).view(-1, 1, 1)*num_points
    idx_base = idx_base.type(torch.cuda.LongTensor)
    idx = idx.type(torch.cuda.LongTensor)
    idx = idx + idx_base
    idx = idx.view(-1)

    _, num_dims, _ = x.size()

    x = x.transpose(2, 1).contiguous()  # (batch_size, num_points, num_dims)  -> (batch_size*num_points, num_dims) #   batch_size * num_points * k + range(0, batch_size*num_points)
    neighbors = x.view(batch_size * num_points, -1)[idx, :]
    neighbors = neighbors.view(batch_size, num_points, k, num_dims)

    neighbors = neighbors.permute(0, 3, 1, 2)  # B,C,N,k
    neighbor_1st = torch.index_select(neighbors, dim=-1, index=torch.cuda.LongTensor([1])) # B,C,N,1
    neighbor_1st = torch.squeeze(neighbor_1st, -1)  # B,3,N
    neighbor_2nd = torch.index_select(neighbors, dim=-1, index=torch.cuda.LongTensor([2])) # B,C,N,1
    neighbor_2nd = torch.squeeze(neighbor_2nd, -1)  # B,3,N

    edge1 = neighbor_1st-org_x
    edge2 = neighbor_2nd-org_x
    normals = torch.cross(edge1, edge2, dim=1) # B,3,N
    dist1 = torch.norm(edge1, dim=1, keepdim=True) # B,1,N
    dist2 = torch.norm(edge2, dim=1, keepdim=True) # B,1,N

    new_pts = torch.cat((org_x, normals, dist1, dist2), 1) # B,8,N
    # new_pts = torch.cat((org_x, normals, edge1, edge2), 1) # B,8,N
    # new_pts = torch.cat((org_x, normals), 1) # B,8,N
    return new_pts

def pw_dist(x):
    inner = -2 * torch.matmul(x.transpose(2, 1), x)
    xx = torch.sum(x ** 2, dim=1, keepdim=True)
    pairwise_distance = -xx - inner - xx.transpose(2, 1)  # (batch_size, num_points, n)

    return -pairwise_distance


def knn_metric(x, d, conv_op1, conv_op2, conv_op11, k):
    batch_size = x.size(0)
    num_points = x.size(2)
    inner = -2 * torch.matmul(x.transpose(2, 1), x)
    xx = torch.sum(x ** 2, dim=1, keepdim=True)
    pairwise_distance = -xx - inner - xx.transpose(2, 1)

    metric = (-pairwise_distance).topk(k=d * k, dim=-1, largest=False)[0]  # B,N,100
    metric_idx = (-pairwise_distance).topk(k=d * k, dim=-1, largest=False)[1]  # B,N,100
    metric_trans = metric.permute(0, 2, 1)  # B,100,N
    metric = conv_op1(metric_trans)  # B,50,N
    metric = torch.squeeze(conv_op11(metric).permute(0, 2, 1), -1)  # B,N
    # normalize function
    metric = torch.sigmoid(-metric)
    # projection function
    metric = 5 * metric + 0.5
    # scaling function

    value1 = torch.where((metric >= 0.5) & (metric < 1.5), torch.full_like(metric, 1), torch.full_like(metric, 0))
    value2 = torch.where((metric >= 1.5) & (metric < 2.5), torch.full_like(metric, 2), torch.full_like(metric, 0))
    value3 = torch.where((metric >= 2.5) & (metric < 3.5), torch.full_like(metric, 3), torch.full_like(metric, 0))
    value4 = torch.where((metric >= 3.5) & (metric < 4.5), torch.full_like(metric, 4), torch.full_like(metric, 0))
    value5 = torch.where((metric >= 4.5) & (metric <= 5.5), torch.full_like(metric, 5), torch.full_like(metric, 0))

    value = value1 + value2 + value3 + value4 + value5 # B,N

    select_idx = torch.cuda.LongTensor(np.arange(k))  # k
    select_idx = torch.unsqueeze(select_idx, 0).repeat(num_points, 1)  # N,k
    select_idx = torch.unsqueeze(select_idx, 0).repeat(batch_size, 1, 1)  # B,N,k
    value = torch.unsqueeze(value, -1).repeat(1, 1, k)  # B,N,k
    select_idx = select_idx * value
    select_idx = select_idx.long()
    idx = pairwise_distance.topk(k=k * d, dim=-1)[1]  # (batch_size, num_points, k*d)
    # dilatedly selecting k from k*d idx
    idx = torch.gather(idx, dim=-1, index=select_idx)  # B,N,k
    return idx



def get_adptive_dilated_graph_feature(x, conv_op1, conv_op2, conv_op11, d=5, k=20, idx=None):
    batch_size = x.size(0)
    num_points = x.size(2)
    x = x.view(batch_size, -1, num_points)
    if idx is None:
        idx = knn_metric(x, d, conv_op1, conv_op2, conv_op11, k=k)  # (batch_size, num_points, k)
    device = torch.device('cuda')
    idx_base = torch.arange(0, batch_size, device=device)
    idx_base = idx_base.view(-1, 1, 1) * num_points
    idx_base = idx_base.type(torch.cuda.LongTensor)
    idx = idx.type(torch.cuda.LongTensor)
    idx = idx + idx_base
    idx = idx.view(-1)
    _, num_dims, _ = x.size()
    x = x.transpose(2,1).contiguous()  # (batch_size, num_points, num_dims)  -> (batch_size*num_points, num_dims) #   batch_size * num_points * k + range(0, batch_size*num_points)
    feature = x.view(batch_size * num_points, -1)[idx, :]
    feature = feature.view(batch_size, num_points, k, num_dims)
    x = x.view(batch_size, num_points, 1, num_dims).repeat(1, 1, k, 1)
    feature = torch.cat((feature - x, x), dim=3).permute(0, 3, 1, 2).contiguous()

    return feature


def square_distance(src, dst):
    """
    Calculate Euclid distance between each two points.
    src^T * dst = xn * xm + yn * ym + zn * zm；
    sum(src^2, dim=-1) = xn*xn + yn*yn + zn*zn;
    sum(dst^2, dim=-1) = xm*xm + ym*ym + zm*zm;
    dist = (xn - xm)^2 + (yn - ym)^2 + (zn - zm)^2
         = sum(src**2,dim=-1)+sum(dst**2,dim=-1)-2*src^T*dst
    Input:
        src: source points, [B, N, C]
        dst: target points, [B, M, C]
    Output:
        dist: per-point square distance, [B, N, M]
    """
    B, N, _ = src.shape
    _, M, _ = dst.shape
    dist = -2 * torch.matmul(src, dst.permute(0, 2, 1))
    dist += torch.sum(src ** 2, -1).view(B, N, 1)
    dist += torch.sum(dst ** 2, -1).view(B, 1, M)
    return dist


def index_points(points, idx):
    """
    Input:
        points: input points data, [B, N, C]
        idx: sample index data, [B, S]
    Return:
        new_points:, indexed points data, [B, S, C]
    """
    device = points.device
    B = points.shape[0]
    view_shape = list(idx.shape)
    view_shape[1:] = [1] * (len(view_shape) - 1)
    repeat_shape = list(idx.shape)
    repeat_shape[0] = 1
    batch_indices = torch.arange(B, dtype=torch.long).to(device).view(view_shape).repeat(repeat_shape)
    new_points = points[batch_indices, idx, :]
    return new_points


def farthest_point_sample(xyz, npoint):
    """
    Input:
        xyz: pointcloud data, [B, N, 3]
        npoint: number of samples
    Return:
        centroids: sampled pointcloud index, [B, npoint]
    """
    device = xyz.device
    B, N, C = xyz.shape
    centroids = torch.zeros(B, npoint, dtype=torch.long).to(device)
    distance = torch.ones(B, N).to(device) * 1e10
    farthest = torch.randint(0, N, (B,), dtype=torch.long).to(device)
    batch_indices = torch.arange(B, dtype=torch.long).to(device)
    for i in range(npoint):
        centroids[:, i] = farthest
        centroid = xyz[batch_indices, farthest, :].view(B, 1, 3)
        dist = torch.sum((xyz - centroid) ** 2, -1)
        distance = torch.min(distance, dist)
        farthest = torch.max(distance, -1)[1]
    return centroids



def knn_point(nsample, xyz, new_xyz):
    """
    Input:
        nsample: max sample number in local region
        xyz: all points, [B, N, C]
        new_xyz: query points, [B, S, C]
    Return:
        group_idx: grouped points index, [B, S, nsample]
    """
    sqrdists = square_distance(new_xyz, xyz)
    _, group_idx = torch.topk(sqrdists, nsample, dim=-1, largest=False, sorted=False)
    return group_idx



class deepconv(nn.Module):
    def __init__(self,in_channel,out_channel,groups):
        super(deepconv, self).__init__()
        self.in_channel = in_channel
        self.out_channel = out_channel
        self.groups = groups
        
        self.conv1 = nn.Sequential(nn.Conv2d(in_channel, in_channel, kernel_size=1,groups=groups,bias=False),
                                  nn.BatchNorm2d(in_channel),
                                  nn.LeakyReLU(negative_slope=0.2)) 
        self.conv2 = nn.Sequential(nn.Conv2d(in_channel, out_channel, kernel_size=1,groups=1,bias=False),
                                  nn.BatchNorm2d(out_channel),
                                  nn.LeakyReLU(negative_slope=0.2))
    def forward(self,x):
        x1 = self.conv1(x)
        x2 = self.conv2(x1)
        x2 = x2.max(dim=-1, keepdim=False)[0]
        return x2
    

        

class DFA(nn.Module):
    def __init__(self,features,M=2,r=1):
        super(DFA,self).__init__()
        self.M = M
        self.features = features
        d = int(self.features / r)
        self.fc = nn.Sequential(nn.Conv1d(self.features, d, kernel_size=1,groups=1,bias=False),
                                  nn.BatchNorm1d(d))
        self.fc1 = nn.Sequential(nn.Conv1d(d, self.features, kernel_size=1,groups=1,bias=False),
                                  nn.BatchNorm1d(self.features))
    def forward(self,x):
        fea_u = x[0]+x[1]
        fea_z = self.fc(fea_u)
        fea_c = self.fc1(fea_z)
        
        att = torch.sigmoid(fea_c)
        fea_v = att*x[0]+(1-att)*x[1]
        return fea_v
    


class Trans2(nn.Module):
    def __init__(self, channels,transform='SS'):
        super(Trans2, self).__init__()

        self.q_layer = nn.Linear(channels,channels)
        self.v_layer = nn.Linear(channels,channels)
        self.k_layer = nn.Linear(channels,channels)
        self.out = nn.Linear(channels,channels)
        self.softmax = nn.Softmax(dim=-1)
        self.transform = transform
        self.alffa = nn.Parameter(torch.zeros(1))
        self.dk = channels
        self.fc_out = nn.Sequential(nn.Linear(channels, channels),
                                    nn.ReLU(),
                                    nn.Linear(channels,channels))
        
        

    def forward(self, x):
        # b, n, c
        B,N,C = x.shape
        x_q = self.q_layer(x)#b,n,c
        # b, c, n
        x_k = self.k_layer(x).permute(0,2,1)#b,c,n
        x_v = self.v_layer(x)#b,n,c
        if self.transform == 'SS':
            att = self.softmax(torch.divide(torch.matmul(x_q, x_k),np.sqrt(self.dk)))
        elif self.transform == 'SL':
            QK = torch.matmul(x_q, x_k)
            att = torch.divide(self.softmax(QK),QK.sum(dim=2).view(B,-1,1))
        x_r = torch.matmul(att, x_v)#b,n,c
        out = self.fc_out(x_r)
        f = self.alffa*out + x
        
        return f
  
  
class CWNET(nn.Module):
    def __init__(self):
        super(GDANET, self).__init__()
        
        self.pointrans1 =Point_Transformer(64) 
        self.pointrans2 =Point_Transformer(64)
        self.pointrans3 =Point_Transformer(128)
        self.pointrans4 =Point_Transformer(256)
        

        self.pt1 = Trans2(64,transform='SS')
        self.pt2 = Trans2(64,transform='SS')
        self.pt3 = Trans2(128,transform='SS')
        self.pt4 = Trans2(256,transform='SS')
        
        self.dc1 = deepconv(16, 64, 16)
        self.dc2 = deepconv(128, 64, 128)
        self.dc3 = deepconv(128, 128, 128)
        self.dc4 = deepconv(256, 256, 256)
        
        self.out = nn.Sequential(nn.Conv1d(512, 1024, 1),
                                 nn.BatchNorm1d(1024),
                                 nn.LeakyReLU(0.2))
 

 
    
 
        self.classifier = nn.Sequential(
                                        nn.Linear(1024*2, 512),
                                        nn.BatchNorm1d(512),
                                        nn.LeakyReLU(negative_slope=0.2),
                                        nn.Dropout(0.5),
                                        nn.Linear(512, 256),
                                        nn.BatchNorm1d(256),
                                        nn.LeakyReLU(negative_slope=0.2),
                                        nn.Dropout(0.5),
                                        nn.Linear(256, 40)
                                        )
        

        
        self.dfa1 = DFA(features=64,M=2,r=1)
        self.dfa2 = DFA(features=64,M=2,r=1)
        self.dfa3 = DFA(features=128,M=2,r=1)
        self.dfa4 = DFA(features=256,M=2,r=1)

       
    

    def forward(self, x):
        B, C, N = x.size()
        xyz = x 
        
        x = geometric_point_descriptor(x)
        # x = self.embedding(x)#B 32 N
      
        x1 = get_graph_feature(x, k=20)
        x1 = self.dc1(x1)
        x1_t = self.pointrans1(xyz,x1,k=20)
        # print(x1_t.shape)
        
        x2 = get_graph_feature(x1_t, k=20)
        x2 = self.dc2(x2)
        x2s = x2.permute(0,2,1)
        x2s = self.pt2(x2s)
        x2_t = self.dfa2([x2,x2s.permute(0,2,1)])

        
        x3 = get_graph_feature(x2_t, k=20)
        x3 = self.dc3(x3)
        x3s = x3.permute(0,2,1)
        x3s = self.pt3(x3s)
        x3_t = self.dfa3([x3,x3s.permute(0,2,1)])
        
        x4 = get_graph_feature(x3_t, k=20)
        x4 = self.dc4(x4)
        x4s = x4.permute(0,2,1)
        x4s = self.pt4(x4s)
        x4_t = self.dfa4([x4,x4s.permute(0,2,1)])

        
        x = torch.cat((x1_t,x2_t,x3_t,x4_t),dim=1)
        
        x = self.out(x)
        
        x11 = F.adaptive_avg_pool1d(x,1).view(B,-1)
        x12 = F.adaptive_max_pool1d(x,1).view(B,-1)
        
        x = torch.cat((x11,x12),dim=-1)
        x = self.classifier(x)
        
    
        return x

# if __name__ == '__main__':
#     data_size = (1,3,1024)
#     data = torch.randn(data_size)
#     model = GDANET()
#     print("===> testing pointMLP ...")
#     device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
#     model.to(device)
#     summary(model, input_size=data_size)
#     # flops = torch.cuda.get_flops(model, input_size=data_size)
#     # print("Total FLOPs:", flops)
#     # flops, params = profile(model, inputs=(data),verbose=False)
#     # flops, params = clever_format([flops,params])
#     # out = model(data)
#     # print(f'FLOPs:{flops}')
#     # print(f'Params:{params}')
