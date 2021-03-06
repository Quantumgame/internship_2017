"""Run the transfer experiment on the AVLetters dataset.

All of the runned experiments are not included here, but one can refer
to this file to see what are the classses to use and how the methods
are called. By varying a little the arguments we can replicate the
results described in the report.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from audio import CNN_mfcc6
from video import CNN_lips5

from multimodal.AVSR import TrainClassifyAudioAVSR
from multimodal.AVSR import EvaluateClassifyAudioAVSR
from multimodal.AVSR import TrainClassifyVideoAVSR
from multimodal.AVSR import EvaluateClassifyVideoAVSR
from multimodal.AVSR import TrainClassifyVideoAVSRAT
from multimodal.AVSR import TrainTransfer, EvaluateTransfer


class TransferTest(object):

    tfrecord_dir = '../dataset/avletters/tfrecords/mfcc_lips_transfer'
    log_dir_audio = 'test/log/tranfer/audio'
    log_dir_video_AT = 'test/log/transfer/video_AT'
    log_dir_video_all = 'test/log/tranfer/video_all'
    log_dir_transfer = 'test/log/transfer/main'

    def train_audio(self, num_steps):
        TrainClassifyAudioAVSR(CNN_mfcc6).train(
            self.tfrecord_dir, None, self.log_dir_audio, num_steps,
            weight_decay=0.1)

    def evaluate_audio(self, split_name):
        EvaluateClassifyAudioAVSR(CNN_mfcc6).evaluate(
            self.tfrecord_dir, self.log_dir_audio, None,
            batch_size=None, split_name=split_name)

    def train_video_all(self, num_steps):
        TrainClassifyVideoAVSR.train(CNN_lips5, initial_learning_rate=2e-3,
                                     lr_decay_rate=0.96).train(
            self.tfrecord_dir, None, self.log_dir_video_all, num_steps)

    def evaluate_video_all(self, split_name):
        EvaluateClassifyVideoAVSR(CNN_lips5).evaluate(
            self.tfrecord_dir, self.log_dir_video_all, None,
            batch_size=None, split_name=split_name)

    def train_video_AT(self, num_steps):
        TrainClassifyVideoAVSRAT(CNN_lips5, initial_learning_rate=2e-3,
                                 lr_decay_rate=0.96).train(
            self.tfrecord_dir, None, self.log_dir_video_AT, num_steps)

    def evaluate_video_AT(self, split_name):
        EvaluateClassifyVideoAVSR(CNN_lips5).evaluate(
            self.tfrecord_dir, self.log_dir_video_AT, None,
            batch_size=None, split_name=split_name)

    def train_transfer(self, num_steps):
        TrainTransfer(audio_architecture=CNN_mfcc6,
                      video_architecture=CNN_lips5,
                      initial_learning_rate=1e-3, lr_decay_rate=0.8).train(
            self.tfrecord_dir, [self.log_dir_audio, self.log_dir_video_AT],
            self.log_dir_transfer, num_steps, K=12, use_audio_prob=0.8)

    def evaluate_transfer(self, split_name):
        EvaluateTransfer(CNN_lips5).evaluate(
            self.tfrecord_dir, self.log_dir_transfer, None,
            batch_size=None, split_name=split_name, shuffle=False)
