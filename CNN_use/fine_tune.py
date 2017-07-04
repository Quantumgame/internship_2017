from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from six.moves import xrange

import os
import time

import numpy as np
import tensorflow as tf
from nets import inception_v4

import data.images.read_TFRecord as read_TFRecord
from data.images.load_batch import load_batch


slim = tf.contrib.slim


def get_init_fn(checkpoints_dir, exclude=None):
    """Returns a function run by the chief worker to
       warm-start the training."""
    if exclude is None:
        checkpoint_exclude_scopes = [
            'InceptionV4/Logits', 'InceptionV4/AuxLogits']
    else:
        checkpoint_exclude_scopes = exclude

    exclusions = [scope.strip() for scope in checkpoint_exclude_scopes]

    variables_to_restore = []
    for var in tf.model_variables():
        excluded = False
        for exclusion in exclusions:
            if var.op.name.startswith(exclusion):
                excluded = True
                break
        if not excluded:
            variables_to_restore.append(var)

    if tf.train.checkpoint_exists(checkpoints_dir):
        checkpoint_path = tf.train.latest_checkpoint(checkpoints_dir)
    else:
        checkpoint_path = os.path.join(checkpoints_dir, 'inception_v4.ckpt')

    return slim.assign_from_checkpoint_fn(
        checkpoint_path, variables_to_restore)


def get_variables_to_train(scopes):
    variables_to_train = []
    for scope in scopes:
        variables = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope)
        variables_to_train.extend(variables)
    return variables_to_train


def train_step(sess, train_op, global_step, metrics_op, *args):

    tensors_to_run = [train_op, global_step, metrics_op]
    tensors_to_run.extend(args)

    start_time = time.time()
    tensor_values = sess.run(tensors_to_run, feed_dict={'training:0': True})
    time_elapsed = time.time() - start_time

    total_loss = tensor_values[0]
    global_step_count = tensor_values[1]

    tf.logging.info(
        'global step %s: loss: %.4f (%.2f sec/step)',
        global_step_count, total_loss, time_elapsed)

    return tensor_values


def fine_tune(dataset_dir,
              checkpoints_dir,
              log_dir,
              number_of_steps=None,
              number_of_epochs=5,
              batch_size=24,
              save_summaries_steps=5,
              do_test=False,
              trainable_scopes=None,
              initial_learning_rate=0.005,
              lr_decay_steps=100,
              lr_decay_rate=0.8):
    """Fine tune a pre-trained model using customized dataset.

    Args:
        dataset_dir: The directory that contains the tfreocrd files
          (which can be generated by data/convert_TFrecord.py)
        checkpoints_dir: The directory containing the checkpoint of
          the model to use
        log_dir: The directory to log event files and checkpoints
        number_of_steps: number of steps to run the training process
          (one step = one batch), if is None then number_of_epochs is used
        number_of_epochs: Number of epochs to run through the whole dataset
        batch_size: The batch size used to train and test (if any)
        save_summaries_steps: We save the summary every save_summaries_steps
        do_test: If True the test is done every save_summaries_steps and
          is shown on tensorboard
        trainable_scopes: The layers to train
    """
    if not tf.gfile.Exists(log_dir):
        tf.gfile.MakeDirs(log_dir)

    image_size = 299

    with tf.Graph().as_default():

        tf.logging.set_verbosity(tf.logging.INFO)

        with tf.name_scope('data_provider'):
            dataset = read_TFRecord.get_split('train', dataset_dir)

            # Don't crop images
            images, _, labels = load_batch(
                dataset, height=image_size, width=image_size,
                batch_size=batch_size, is_training=False)

            # Test propose
            dataset_test = read_TFRecord.get_split('validation', dataset_dir)

            images_test, _, labels_test = load_batch(
                dataset_test, height=image_size, width=image_size,
                batch_size=batch_size, is_training=False)

        if number_of_steps is None:
            number_of_steps = int(np.ceil(
                dataset.num_samples * number_of_epochs / batch_size))

        # Decide if we're training or not
        training = tf.placeholder(tf.bool, shape=(), name='training')
        images = tf.cond(training, lambda: images, lambda: images_test)
        labels = tf.cond(training, lambda: labels, lambda: labels_test)

        # Create the model, use the default arg scope to configure the
        # batch norm parameters
        with slim.arg_scope(
                inception_v4.inception_v4_arg_scope(batch_norm_decay=0.9)):
            logits, end_points = inception_v4.inception_v4(
                images, num_classes=dataset.num_classes,
                is_training=training)

        # Specify the loss function
        one_hot_labels = tf.one_hot(labels, dataset.num_classes)
        tf.losses.softmax_cross_entropy(one_hot_labels, logits)
        total_loss = tf.losses.get_total_loss()

        # Create the global step for monitoring training
        global_step = tf.train.get_or_create_global_step()

        # Exponentially decaying learning rate
        learning_rate = tf.train.exponential_decay(
            learning_rate=initial_learning_rate,
            global_step=global_step,
            decay_steps=lr_decay_steps,
            decay_rate=lr_decay_rate, staircase=True)

        # Specify the optimizer and create the train op:
        optimizer = tf.train.AdamOptimizer(learning_rate=learning_rate)

        if trainable_scopes is None:
            trainable_scopes = [
                'InceptionV4/Mixed_7d',
                'InceptionV4/Logits',
                'InceptionV4/AuxLogits']
        variables_to_train = get_variables_to_train(trainable_scopes)

        # print(variables_to_train)
        train_op = slim.learning.create_train_op(
            total_loss, optimizer,
            variables_to_train=variables_to_train)

        # The metrics to predict
        predictions = tf.argmax(end_points['Predictions'], 1)
        accuracy, accuracy_update = tf.metrics.accuracy(predictions, labels)
        accuracy_test = tf.reduce_mean(tf.cast(
            tf.equal(predictions, labels), tf.float32))
        metrics_op = tf.group(accuracy_update)

        # Track moving mean and moving varaince
        last_moving_mean = [v for v in tf.model_variables()
                            if v.op.name.endswith('moving_mean')][0]
        last_moving_variance = [v for v in tf.model_variables()
                                if v.op.name.endswith('moving_variance')][0]

        # Create some summaries to visualize the training process:
        tf.summary.scalar('learning_rate', learning_rate)
        tf.summary.histogram('logits', logits)
        tf.summary.histogram('batch_norm/last_layer/moving_mean',
                             last_moving_mean)
        tf.summary.histogram('batch_norm/last_layer/moving_variance',
                             last_moving_variance)
        tf.summary.scalar('losses/train/total_loss', total_loss)
        tf.summary.scalar('accuracy/train/streaming', accuracy)
        tf.summary.image('train', images, max_outputs=6)
        summary_op = tf.summary.merge_all()

        # Summaries for the test part
        ac_test_summary = tf.summary.scalar('accuracy/test', accuracy_test)
        ls_test_summary = tf.summary.scalar(
            'losses/test/total_loss', total_loss)
        imgs_test_summary = tf.summary.image(
            'test', images, max_outputs=6)
        test_summary_op = tf.summary.merge(
            [ac_test_summary, ls_test_summary, imgs_test_summary])

        # Define the supervisor
        sv = tf.train.Supervisor(
            logdir=log_dir, summary_op=None,
            init_fn=get_init_fn(checkpoints_dir))

        with sv.managed_session() as sess:

            for step in xrange(number_of_steps):
                if (step+1) % save_summaries_steps == 0:
                    loss, _, _, summaries, accuracy_rate = train_step(
                        sess, train_op, sv.global_step, metrics_op,
                        summary_op, accuracy)
                    tf.logging.info('Current Streaming Accuracy:%s',
                                    accuracy_rate)
                    sv.summary_computed(sess, summaries)
                    if do_test:
                        ls, acu, summaries_test = sess.run(
                            [total_loss, accuracy_test, test_summary_op],
                            feed_dict={training: False})
                        tf.logging.info('Current Test Loss: %s', ls)
                        tf.logging.info('Current Test Accuracy: %s', acu)
                        sv.summary_computed(sess, summaries_test)
                else:
                    loss = train_step(
                        sess, train_op, sv.global_step, metrics_op)[0]

            tf.logging.info('Finished training. Final Loss: %s', loss)
            tf.logging.info('Final Accuracy: %s', sess.run(accuracy))
            tf.logging.info('Saving model to disk now.')
            sv.saver.save(sess, sv.save_path, global_step=sv.global_step)