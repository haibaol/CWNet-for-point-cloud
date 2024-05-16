# Learning Geometry-Disentangled Representation for Complementary Understanding of 3D Object Point Cloud.
This repository is built for the paper:


## Installation


### Requirements
* Linux (tested on Ubuntu 14.04/16.04)
* Python 3.5+
* PyTorch 1.0+

### Dataset
* Create the folder to symlink the data later:

    `mkdir -p data`

* __Object Classification__:

    Download and unzip [ModelNet40](https://shapenet.cs.stanford.edu/media/modelnet40_ply_hdf5_2048.zip) (415M), then symlink the path to it as follows (you can alternatively modify the path [here](https://github.com/mutianxu/GDANet/blob/main/util/data_util.py#L12)) :

    `ln -s /path to modelnet40/modelnet40_ply_hdf5_2048 data`

* __Shape Part Segmentation__:

    Download and unzip [ShapeNet Part](https://shapenet.cs.stanford.edu/media/shapenetcore_partanno_segmentation_benchmark_v0_normal.zip) (674M), then symlink the path to it as follows (you can alternatively modify the path [here](https://github.com/mutianxu/GDANet/blob/main/util/data_util.py#L70)) :

    `ln -s /path to shapenet part/shapenetcore_partanno_segmentation_benchmark_v0_normal data`

## Usage

### Object Classification on ModelNet40
* Train:

    `python main_cls.py`

* Test:

    * You can also directly evaluate our pretrained model without voting :

        `python main.py --eval True --model_path 

### Shape Part Segmentation on ShapeNet Part
* Train:
    * Training from scratch:

        `python main_ptseg.py`

    * If you want resume training from checkpoints, specify `resume` in the args:

        `python main_ptseg.py --resume True`

* Test:

    You can choose to test the model with the best instance mIoU, class mIoU or accuracy, by specifying `eval` and `model_type` in the args:

    * `python main_ptseg.py --eval True --model_type 'insiou'` (best instance mIoU, default)

    * `python main_ptseg.py --eval True --model_type 'acc'` (best accuracy)

    **Note**: This works only after you trained the model or if you have the checkpoint in `checkpoints/CWNet`. If you run the training from scratch the checkpoints will automatically be generated there.
 

## Performance
The following tables report the current performances on different tasks and datasets.

### Object Classification on ModelNet40

| Method | mAcc | OA |
| :--- | :---: | :---: |
| GDANet      | **91.0%**| **93.7%** |

### Object Classification on ScanObjectNN

| Method | mAcc | OA |
| :--- | :---: | :---: |
| GDANet      |  **81.3%**  | **83.2%** |

### Shape Part Segmentation on ShapeNet Part
| Method  | Instance mIoU |
| :--- | :---: |
| GDANet    | **86.0%** |

## Other information

Please contact Kaihao Feng (fengkaihao_666@163.com) for further discussion.

## Acknowledgement
This code is is partially borrowed from [DGCNN](https://github.com/WangYueFt/dgcnn) and [PointNet++](https://github.com/charlesq34/pointnet2).  

## Update


