path_r = r"32121++_train.log.txt"
with open(path_r, "r") as f:  # 打开文件
    data = f.read()  # 读取文件
path_w = r"32121++_train.log.txt"
with open(path_w, "w") as f:    # 以写的方式打开结果文件
    i = -1  # 用来记录本次循环数据所在位置
    j = data.rfind('train acc:  ')   # 找到最后一条数据所在的位置
    while i < j:
        start = i+1  # 每次查找都要从上一条数据之后的位置开始，默认从0开始
        i = data.index('train acc: ', start)    # 从start开始查找，返回now第一次出现的位置
        # result = data[i+10:i+18]     # i+4是从now的位置往后移，也就是说去掉“now=”，i+14是指数值部分只取10位
        result = data[i + 1:i + 9]  # acg_acc

        f.write(result)  # 把数值写入文件，自带文件关闭功能，不需要再写f.close()
        f.write('\n')   # 换行




