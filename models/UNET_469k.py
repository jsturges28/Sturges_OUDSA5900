# -*- coding: utf-8 -*-
"""
Created on Tue Nov  8 19:55:00 2022

@author: jstur2828
"""

import math
import tensorflow as tf
import numpy as np
import matplotlib.pyplot as plt
import tensorflow.keras as keras
import keras.backend as K
import pickle
import os
import cv2
import time
import csv
import tensorflow_addons as tfa
import argparse
import re
import sys

# Append paths so python can find our callback class

sys.path.append(os.getcwd()) # if we're in the main directory
sys.path.append(os.path.dirname(os.getcwd())) # if we're in the models folder

import callbacks
from callbacks import StopOnAccuracy

from tensorflow.keras.models import Model
from tensorflow.keras.datasets import mnist
from tensorflow.keras.utils import to_categorical
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, MaxPooling2D, Flatten, \
    Convolution2D, Activation, Dropout, LSTM, \
    Convolution3D, MaxPooling3D, Conv2DTranspose, Conv3DTranspose, \
    Attention, Input, ZeroPadding2D, Cropping2D
from keras.optimizers import Adam
from keras.callbacks import History, EarlyStopping
from math import ceil

# Go one level up if we're in the models folder 

if 'models' in os.getcwd():
    os.chdir('../')

# Assign path to cwd
path = os.getcwd()
model_type = 'UNET'

'''
Dice and IOU metrics
'''

def dice_coef(y_true, y_pred, smooth=100):        
    y_true_f = K.flatten(y_true)
    y_pred_f = K.flatten(y_pred)
    intersection = K.sum(y_true_f * y_pred_f)
    dice = (2. * intersection + smooth) / (K.sum(y_true_f) + K.sum(y_pred_f) + smooth)
    return dice

def dice_coef_loss(y_true, y_pred):
    return 1 - dice_coef(y_true, y_pred)

# Start at experiment 0. Then, every time this is run, we can increment the index to the next experiment without having to do it manually.

def get_last_exp_index(path, folder):
    if os.path.exists(os.path.join(path, folder)):
        files = [f for f in os.listdir(os.path.join(path, folder))]
        if files:
            matches = []
            digits = []

            for file in files:
                file_matches = re.findall(r'.*UNET.*', file)
                matches.extend(file_matches)
            matches.sort()
            
            if len(matches) == 0:
                return 0
            
            for match in matches:
                digit_match = re.findall(r'\d+', match)
                digits.extend(digit_match)
            digits.sort()
            
            last_index = digits[-1]
            return int(last_index) + 1
        else:
            return 0
    else: 
        return 0
    
# Create global variable to retrieve the last index in the filesystem, feed it into the parser automatically

last_index = get_last_exp_index(path, 'results')

def create_parser():
    '''
    Creates an argument parser for the program to run in command line. Can also run in program if no specification is needed.
    '''
    
    parser = argparse.ArgumentParser(description='UNET')
    
    parser.add_argument('--exp', type=int, nargs='?', const=last_index, default=last_index, help='Experimental index')
    parser.add_argument('--epochs', type=int, nargs='?', const=20, default=20, help='Number of training epochs')
    parser.add_argument('--val_acc', type=float, nargs='?', const=0.95, default=0.95, help='Max accuracy before model stops training')
    parser.add_argument('--min_delta', type=float, nargs='?', const=0.005, default=0.005, help='Minimum training accuracy improvement for each epoch')
    parser.add_argument('--no_display', action='store_false', help='Dont display set of learning curve(s) after running experiment(s)')
    #parser.add_argument('--run_exp', type=int, nargs='?', const=1, default=1, help='Select number of times to run experiment')
    parser.add_argument('--batch_size', type=int, nargs='?', const=50, default=50, help='Set size of batch')
    parser.add_argument('--no_results', action='store_false', help='Skip predicting values and dont display the handwritten digits')
    parser.add_argument('--no_verbose', action='store_false', help='Skip the display training progress and dont print results to screen')
    
    return parser

def args2string(args):
    '''
    Translate the current set of arguments
    
    :param args: Command line arguments
    '''
    return "exp_%02d_UNET"%(args.exp)

def display_iou_set(path, folder):
    '''
    Plot the learning curves for a set of results
    
    :param base: Directory containing a set of results files
    '''
    
    files = [f for f in os.listdir(os.path.join(path, folder))]
    if files:
        matches = []

        for file in files:
            file_matches = re.findall(r'.*UNET.*', file)
            matches.extend(file_matches)
        matches.sort()
        
    plt.figure()
    for f in matches:
        with open("%s/%s"%(os.path.join(path, folder),f), "rb") as fp:
            history = pickle.load(fp)
            #time = pickle.loads(fp.readline())
            for key, value in history.items():
                # iter on both keys and values
                if key.startswith('val_mean_io_u'):
                    iou = key
            plt.ylim(0,1)
            plt.plot(history[iou])
    plt.title("Test IOU vs. Epochs")
    plt.ylabel('IOU score')
    plt.xlabel('Epochs')
    plt.legend(matches, fontsize='small', loc='lower left', ncol=2)
    
parser = create_parser()
args = parser.parse_args()

train, test = (.9, .1)
segmented = np.load('C:\\Users\\jstur2828\\Desktop\\UNET\\segmented\\segmented.npy')
_, height, width, c_size = segmented.shape

combined=np.load('C:\\Users\\jstur2828\\Desktop\\UNET\\combined\\combined.npy')

train_data = combined[:int(len(combined)*train),:,:]
train_label = segmented[:int(len(combined)*train),:,:,:]
test_data = combined[int(len(combined)*train):,:,:]
test_label = segmented[int(len(combined)*train):,:,:,:]

#combined.reshape((-1, height, width, 1))/255

'''
rand_index = np.random.randint(0,len(combined))
c,s = combined[rand_index], segmented[rand_index]
plt.figure(figsize=(5,5))
plt.imshow(c)
plt.show()

for i in range(10):
    plt.figure(figsize=(5,5))
    plt.imshow(s[:,:,i])
    plt.title(i)
    plt.show()
'''

def build(height, width, c_size):
    
    input_layer = keras.layers.Input(shape=[height, width, c_size])
    
    #padding1 = ZeroPadding2D(padding=11, input_shape=[height, width, c_size])(input_layer)
    
    conv1 = Convolution2D(32, (3,3), padding="same", activation='relu')(input_layer)
    conv2 = Convolution2D(32, (3,3), padding="same", activation='relu')(conv1)
    maxpool1 = MaxPooling2D(pool_size=(2,2))(conv2)
    
    conv3 = Convolution2D(64, (3,3), padding="same", activation='relu')(maxpool1)
    conv4 = Convolution2D(64, (3,3), padding="same", activation='relu')(conv3)
    maxpool2 = MaxPooling2D(pool_size=(2,2))(conv4)
    
    conv5 = Convolution2D(128, (3,3), padding="same", activation='relu')(maxpool2)
    conv6 = Convolution2D(128, (3,3), padding="same", activation='relu')(conv5)                            
    up_conv1 = Conv2DTranspose(filters=64, strides=(2,2), kernel_size=(2,2))(conv6)
    
    for i in range(1,3):
        if (K.int_shape(conv4)[1] == K.int_shape(up_conv1)[1] and K.int_shape(conv4)[2] == K.int_shape(up_conv1)[2]):
            merge1 = tf.keras.layers.concatenate([conv4, up_conv1], axis=-1)
            break
        else:
            diff = K.int_shape(conv4)[i] - K.int_shape(up_conv1)[i]
            while(diff):
                if diff < 0 and i == 1:
                    pad_width = abs(int(ceil(diff/2)))
                    if pad_width == 0:
                        pad_width = 1
                    conv4 = ZeroPadding2D(padding=((0,pad_width),(0,0)))(conv4)
                    diff = K.int_shape(conv4)[i] - K.int_shape(up_conv1)[i]
                
                if diff < 0 and i == 2:
                    pad_width = abs(int(ceil(diff/2)))
                    if pad_width == 0:
                        pad_width = 1
                    conv4 = ZeroPadding2D(padding=((0,0),(0,pad_width)))(conv4)
                    diff = K.int_shape(conv4)[i] - K.int_shape(up_conv1)[i]
            
                if diff > 0 and i == 1:
                    conv4 = Cropping2D(cropping=((1,0), (0,0)))(conv4)
                    diff = K.int_shape(conv4)[i] - K.int_shape(up_conv1)[i]
                elif diff > 0 and i == 2:
                    conv4 = Cropping2D(cropping=((0,0), (0,1)))(conv4)
                    diff = K.int_shape(conv4)[i] - K.int_shape(up_conv1)[i]
                    
    merge1 = tf.keras.layers.concatenate([conv4, up_conv1], axis=-1)
    
    conv7 = Convolution2D(64, (3,3), padding="same", activation='relu')(merge1)
    conv8 = Convolution2D(64, (3,3), padding="same", activation='relu')(conv7)                             
    up_conv2 = Conv2DTranspose(filters=32, strides=(2,2), kernel_size=(2,2))(conv8)
    
    for i in range(1,3):
        if (K.int_shape(conv2)[1] == K.int_shape(up_conv2)[1] and K.int_shape(conv2)[2] == K.int_shape(up_conv2)[2]):
            merge2 = tf.keras.layers.concatenate([conv2, up_conv2], axis=-1)
            break
        else:
            diff = K.int_shape(conv2)[i] - K.int_shape(up_conv2)[i]
            while(diff):
                if diff < 0 and i == 1:
                    pad_width = abs(int(ceil(diff/2)))
                    if pad_width == 0:
                        pad_width = 1
                    conv2 = ZeroPadding2D(padding=((0,pad_width),(0,0)))(conv2)
                    diff = K.int_shape(conv2)[i] - K.int_shape(up_conv2)[i]
                    
                if diff < 0 and i == 2:
                    pad_width = abs(int(ceil(diff/2)))
                    if pad_width == 0:
                        pad_width = 1
                    conv2 = ZeroPadding2D(padding=((0,0),(0,pad_width)))(conv2)
                    diff = K.int_shape(conv2)[i] - K.int_shape(up_conv2)[i]
                
            
                if diff > 0 and i == 1:
                    conv2 = Cropping2D(cropping=((1,0), (0,0)))(conv2)
                    diff = K.int_shape(conv2)[i] - K.int_shape(up_conv2)[i]
                elif diff > 0 and i == 2:
                    conv2 = Cropping2D(cropping=((0,0), (0,1)))(conv2)
                    diff = K.int_shape(conv2)[i] - K.int_shape(up_conv2)[i]
                    
    merge2 = tf.keras.layers.concatenate([conv2, up_conv2], axis=-1)
    
    conv9 = Convolution2D(32, (3,3), padding="same", activation='relu')(merge2)
    conv10 = Convolution2D(32, (3,3), padding="same", activation='relu')(conv9)                          
    
    conv11 = Convolution2D(11, 1, padding="same")(conv10)
    act1 = Activation("softmax")(conv11)
    
    return keras.Model(inputs=input_layer,outputs=act1)

# Create an EarlyStopping callback that stops training when the training accuracy doesn't improve by 0.005 over 2 epochs

callback = EarlyStopping(monitor='accuracy', patience=2, min_delta=args.min_delta)

# Create a StopOnAccuracy callback that stops training when the testing accuracy reaches 93%

stop_on_accuracy = StopOnAccuracy(args.val_acc)
    
model = build(height, width, 1)

print(model.summary())


model.compile(loss='binary_crossentropy', optimizer=keras.optimizers.Adam(0.001), metrics=['accuracy', tf.keras.metrics.MeanIoU(num_classes=2)])

argstring = args2string(args)
print("EXPERIMENT: %s"%argstring)

start_time = time.time()
history = model.fit(combined, segmented, validation_split=0.33, batch_size=args.batch_size, epochs=args.epochs, verbose=args.no_verbose, callbacks=[callback, stop_on_accuracy])
end_time = time.time()
tot_time = float("%.2f"%(end_time - start_time))

if not os.path.exists(os.path.join(path, "results")):
    os.mkdir(os.path.join(path, "results"))

res_path = os.path.join(path, "results")
    
fp = open("results\\results_%s.pkl"%(argstring), "wb")
pickle.dump(history.history, fp)
#pickle.dump(args, fp)
fp.write(b"\n")
pickle.dump(tot_time, fp)
fp.close()

def print_test(N_TEST, HEIGHT, WIDTH, combined_test, segmented_test, model):
    rand_index = np.random.randint(0,len(combined_test))
    combined_test=np.reshape(combined_test,(len(combined_test),HEIGHT,WIDTH,1))
    segmented_test=np.reshape(segmented_test,(len(segmented_test),HEIGHT,WIDTH,11))
    originals = combined_test[rand_index:rand_index+N_TEST,:,:,:]
    ground_truth = segmented_test[rand_index:rand_index+N_TEST,:,:,:]
    maxig = np.argmax(ground_truth[0], axis=2)
    predicted = model.predict(originals)
    predicted = np.round(predicted).astype(int)
    maxi = np.argmax(predicted[0], axis=2)
    plt.figure(figsize=(8, 11))
    plt.suptitle('UNET image recreations on 3 random images')
    for i in range(N_TEST):
        plt.subplot(4, N_TEST, i+1)
        plt.imshow(originals[i].reshape((HEIGHT, WIDTH)))
        plt.gca().title.set_text("Original image")
        plt.subplot(4, N_TEST, i+1+N_TEST)
        plt.imshow(np.argmax(predicted[i], axis=2))
        plt.gca().title.set_text("Predicted image")
        plt.subplot(4, N_TEST, i+1+2*N_TEST)
        plt.imshow(np.argmax(ground_truth[i], axis=2))
        plt.gca().title.set_text("Ground truth")
        
if not os.path.exists(os.path.join(path, "figures")):
    os.mkdir(os.path.join(path, "figures"))
fig_path = os.path.join(path, "figures")

# This looks weird, but the boolean argument was set to false as default. So, invoking --no_results will return false and the loop won't run.

if args.no_results:
    print_test(3, 64, 84, combined, segmented, model)
    plt.savefig(os.path.join(fig_path,'predicted_digits_%s.png'%argstring))
    plt.close()

#history_dict = history.history

'''
plt.plot(history.history['accuracy'])
plt.plot(history.history['val_accuracy'])
plt.title('model accuracy')
plt.ylabel('accuracy')
plt.xlabel('epoch')
plt.legend(['train', 'test'], loc='upper left')
plt.show()

plt.plot(history.history['loss'])
plt.plot(history.history['val_loss'])
plt.title('model loss')
plt.ylabel('loss')
plt.xlabel('epoch')
plt.legend(['train', 'test'], loc='upper right')
plt.show()
'''

# This looks weird, but the boolean argument was set to false as default. So, invoking --no_display will return false and the loop won't run.
if args.no_display:
    display_iou_set(path, 'results')
    plt.savefig(os.path.join(fig_path,'results_%s.png'%argstring))
    plt.close()

#print("Epoch stopped at epoch", callback.stopped_epoch)

# This looks weird, but the boolean argument was set to false as default. So, invoking --no_verbose will return false and the loop won't run.
if args.no_verbose:
    #get number of epochs
    print("Number of epochs run:", len(history.history['accuracy']))
    print("IOU score:", float("%.4f"%history.history['val_mean_io_u'][-1]))
    print("Time to run model: ", tot_time, "seconds")
    
file = open('unet_times.txt')
file.write(str(tot_time)+'\r\n')
file.close()

