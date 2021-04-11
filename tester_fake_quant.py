from onnx_torch_engine.torch_quanter import *
from onnx_optimizer.optimizer import *
import onnx
import os
import sys

import argparse
import numpy as np
import json
import onnxruntime as rt
import cv2
class DecodeImage(object):
    def __init__(self, to_rgb=True):
        self.to_rgb = to_rgb

    def __call__(self, img):
        data = np.frombuffer(img, dtype='uint8')
        img = cv2.imdecode(data, 1)
        if self.to_rgb:
            assert img.shape[2] == 3, 'invalid shape of image[%s]' % (
                img.shape)
            img = img[:, :, ::-1]

        return img


class ResizeImage(object):
    def __init__(self, resize_short=None):
        self.resize_short = resize_short

    def __call__(self, img):
        img_h, img_w = img.shape[:2]
        percent = float(self.resize_short) / min(img_w, img_h)
        w = int(round(img_w * percent))
        h = int(round(img_h * percent))
        return cv2.resize(img, (h,w))


class CropImage(object):
    def __init__(self, size):
        if type(size) is int:
            self.size = (size, size)
        else:
            self.size = size

    def __call__(self, img):
        w, h = self.size
        img_h, img_w = img.shape[:2]
        w_start = (img_w - w) // 2
        h_start = (img_h - h) // 2

        w_end = w_start + w
        h_end = h_start + h
        return img[h_start:h_end, w_start:w_end, :]


class NormalizeImage(object):
    def __init__(self, scale=None, mean=None, std=None):
        self.scale = np.float32(scale if scale is not None else 1.0 / 255.0)
        mean = mean if mean is not None else [0.485, 0.456, 0.406]
        std = std if std is not None else [0.229, 0.224, 0.225]

        shape = (1, 1, 3)
        self.mean = np.array(mean).reshape(shape).astype('float32')
        self.std = np.array(std).reshape(shape).astype('float32')

    def __call__(self, img):
        return (img.astype('float32') * self.scale - self.mean) / self.std


class ToTensor(object):
    def __init__(self):
        pass

    def __call__(self, img):
        img = img.transpose((2, 0, 1))
        return img
def parse_args():
    def str2bool(v):
        return v.lower() in ("true", "t", "1")

    parser = argparse.ArgumentParser()
    # parser.add_argument("-i", "--image_file", type=str,default="/home/gong/datasets/images")
    # parser.add_argument("-m", "--model", type=str, default=None)
    # parser.add_argument("-p", "--pretrained_model",type=str,  default="/home/gong/onnx_quanter/bn_fold_ResNet_v1_50.onnx")
    # parser.add_argument("-j", "--json_dir", type=str, default="/home/gong/onnx_quanter")
    # parser.add_argument("--use_gpu", type=str2bool, default=True)
    parser.add_argument("-i", "--image_file", type=str,default="/workspace/hgong/images")
    parser.add_argument("-m", "--model", type=str, default=None)
    parser.add_argument("-p", "--pretrained_model",type=str,  default="bn_fold_ResNet_v1_50.onnx")
    parser.add_argument("-j", "--json_dir", type=str, default="")
    parser.add_argument("--use_gpu", type=str2bool, default=True)
    return parser.parse_args()

def softmax(x):
    """Compute softmax values for each sets of scores in x."""
    e_x = np.exp(x - np.max(x))
    return e_x / e_x.sum()

def create_operators():
    size = 224
    img_mean = [0.485, 0.456, 0.406]
    img_std = [0.229, 0.224, 0.225]
    img_scale = 1.0 / 255.0

    decode_op = DecodeImage()
    resize_op = ResizeImage(resize_short=256)
    crop_op = CropImage(size=(size, size))
    normalize_op = NormalizeImage(
        scale=img_scale, mean=img_mean, std=img_std)
    totensor_op = ToTensor()

    return [decode_op, resize_op, crop_op ,normalize_op, totensor_op]


def postprocess(outputs, topk=5):
    prob = np.array(outputs[0]).flatten()
    index = prob.argsort(axis=0)[-topk:][::-1].astype('int32')
    return zip(index, prob[index])

def preprocess(fname, ops):
    data = open(fname, 'rb').read()
    for op in ops:
        data = op(data)

    return data
def get_image_list(img_file):
    imgs_lists = []
    if img_file is None or not os.path.exists(img_file):
        raise Exception("not found any img file in {}".format(img_file))

    img_end = ['jpg', 'png', 'jpeg', 'JPEG', 'JPG', 'bmp']
    if os.path.isfile(img_file) and img_file.split('.')[-1] in img_end:
        imgs_lists.append(img_file)
    elif os.path.isdir(img_file):
        for single_file in os.listdir(img_file):
            if single_file.split('.')[-1] in img_end:
                imgs_lists.append(os.path.join(img_file, single_file))
    if len(imgs_lists) == 0:
        raise Exception("not found any img file in {}".format(img_file))
    return imgs_lists

import onnx
def main():
    args = parse_args()
    # sess = rt.InferenceSession(args.pretrained_model)
    # input_name = sess.get_inputs()[0].name
    # label_name = sess.get_outputs()[0].name
    onnx_model = onnx.load("bn_fold_ResNet_v1_50.onnx")
    cfg={"pad_split":False}
    # onnx_model=simplify(onnx_model)
    model=onnxTorchQuanter(onnx_model,cfg)
    model.eval()
    model.cuda()
    # pred = sess.run([label_name], {input_name: X_test.astype(numpy.float32)})[0]
    operators = create_operators()
    # exe, program, feed_names, fetch_names = load_reference_model(args)

    image_list = get_image_list(args.image_file)

    resultList=[]
    # # os.sys

    for idx, filename in enumerate(image_list):
        data = preprocess(filename, operators)
        data = np.expand_dims(data, axis=0)
        data_torch=torch.Tensor(data).cuda()
        # print(data_torch)
        # pred= sess.run([label_name], {input_name: data})[0]
        with torch.no_grad():
            output=model.calibration(data_torch)
    model.quantilize()

    # for idx, filename in enumerate(image_list):
    #     data = preprocess(filename, operators)
    #     data = np.expand_dims(data, axis=0)
    #     data_torch=torch.Tensor(data).cuda()
    #     # print(data_torch)
    #     # pred= sess.run([label_name], {input_name: data})[0]
    #     with torch.no_grad():
    #         output_float=model(data_torch)
    #         output_quant=model.fake_quant_forward(data_torch)
        
    #     pred_float=output_float.cpu().numpy()
    #     probs_float = postprocess(pred_float)
        
    #     pred_quant=output_quant.cpu().numpy()
    #     probs_quant = postprocess(pred_quant)
        
    #     print("current image: {}".format(filename))
    #     for idx, prob in probs_float:
    #         print("\tclass id: {:d}, probs_float: {:.4f}".format(idx, prob))
    #     for idx, prob in probs_quant:
    #         print("\tclass id: {:d}, probs_quant: {:.4f}".format(idx, prob))



if __name__ == "__main__":
    # enable_static_mode()
    main()



# print(model)