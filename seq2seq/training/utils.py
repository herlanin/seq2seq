"""Miscellaneous training utility functions.
"""

from seq2seq.data.data_utils import read_from_data_provider
import tensorflow as tf
from tensorflow.python.platform import gfile


def get_rnn_cell(cell_type,
                 num_units,
                 num_layers=1,
                 dropout_input_keep_prob=1.0,
                 dropout_output_keep_prob=1.0):
  """Creates a new RNN Cell.

  Args:
    cell_type: A cell lass name defined in `tf.nn.rnn_cell`,
      e.g. `LSTMCell` or `GRUCell`
    num_units: Number of cell units
    num_layers: Number of layers. The cell will be wrapped with
      `tf.nn.rnn_cell.MultiRNNCell`
    dropout_input_keep_prob: Dropout keep probability applied
      to the input of cell *at each layer*
    dropout_output_keep_prob: Dropout keep probability applied
      to the output of cell *at each layer*

  Returns:
    An instance of `tf.nn.rnn_cell.RNNCell`.
  """
  #pylint: disable=redefined-variable-type
  cell_class = getattr(tf.nn.rnn_cell, cell_type)
  cell = cell_class(num_units)

  if dropout_input_keep_prob < 1.0 or dropout_output_keep_prob < 1.0:
    cell = tf.nn.rnn_cell.DropoutWrapper(
        cell=cell,
        input_keep_prob=dropout_input_keep_prob,
        output_keep_prob=dropout_output_keep_prob)

  if num_layers > 1:
    cell = tf.nn.rnn_cell.MultiRNNCell([cell] * num_layers)

  return cell


def create_learning_rate_decay_fn(decay_type,
                                  decay_steps,
                                  decay_rate,
                                  start_decay_at=0,
                                  stop_decay_at=1e9,
                                  min_learning_rate=None,
                                  staircase=False):
  """Creates a function that decays the learning rate.

  Args:
    decay_steps: How often to apply decay.
    decay_rate: A Python number. The decay rate.
    start_decay_at: Don't decay before this step
    stop_decay_at: Don't decay after this step
    min_learning_rate: Don't decay below this number
    decay_type: A decay function name defined in `tf.train`
    staircase: Whether to apply decay in a discrete staircase,
      as opposed to continuous, fashion.

  Returns:
    A function that takes (learning_rate, global_step) as inputs
    and returns the learning rate for the given step.
    Returns `None` if decay_type is empty or None.
  """
  if decay_type is None or decay_type == "":
    return None

  def decay_fn(learning_rate, global_step):
    """The computed learning rate decay function.
    """
    decay_type_fn = getattr(tf.train, decay_type)
    decayed_learning_rate = decay_type_fn(
        learning_rate=learning_rate,
        global_step=tf.minimum(global_step, stop_decay_at) - start_decay_at,
        decay_steps=decay_steps,
        decay_rate=decay_rate,
        staircase=staircase,
        name="decayed_learning_rate")

    final_lr = tf.train.piecewise_constant(
        x=global_step,
        boundaries=[start_decay_at],
        values=[learning_rate, decayed_learning_rate])

    if min_learning_rate:
      final_lr = tf.maximum(final_lr, min_learning_rate)

    return final_lr
  return decay_fn


def create_input_fn(data_provider_fn,
                    featurizer_fn,
                    batch_size,
                    bucket_boundaries=None):
  """Creates an input function that can be used with tf.learn estimators.
    Note that you must pass "factory funcitons" for both the data provider and
    featurizer to ensure that everything will be created in  the same graph.

  Args:
    data_provider_fn: Function that creates a data provider to read from.
      An instance of `tf.contrib.slim.data_provider.DataProvider`.
    featurizer_fn: A function that creates a featurizer function
      which takes tensors returned by the data provider and transfroms them
      into a (features, labels) tuple.
    batch_size: Create batches of this size. A queue to hold a
      reasonable number of batches in memory is created.
    bucket_boundaries: int list, increasing non-negative numbers.
      If None, no bucket is performed.

  Returns:
    An input function that returns `(feature_batch, labels_batch)`
    tuples when called.
  """

  def input_fn():
    """Creates features and labels.
    """
    features = read_from_data_provider(data_provider_fn())
    features, labels = featurizer_fn(features)

    # We need to merge features and labels so we can batch them together.
    feature_keys = features.keys()
    label_keys = labels.keys()
    features_and_labels = features.copy()
    features_and_labels.update(labels)

    if bucket_boundaries:
      bucket_num, batch = tf.contrib.training.bucket_by_sequence_length(
          input_length=features_and_labels["source_len"],
          bucket_boundaries=bucket_boundaries,
          tensors=features_and_labels,
          batch_size=batch_size,
          keep_input=features_and_labels["target_len"] >= 1,
          dynamic_pad=True,
          capacity=5000 + 16 * batch_size,
          name="bucket_queue")
      tf.summary.histogram("buckets", bucket_num)
    else:
      # Filter out examples with target_len < 1
      slice_end = tf.cond(features_and_labels["target_len"] >= 1,
                          lambda: tf.constant(1), lambda: tf.constant(0))
      features_and_labels = {
          k: tf.expand_dims(v, 0)[0:slice_end]
          for k, v in features_and_labels.items()
      }
      batch = tf.train.batch(
          tensors=features_and_labels,
          enqueue_many=True,
          batch_size=batch_size,
          dynamic_pad=True,
          capacity=5000 + 16 * batch_size,
          name="batch_queue")

    # Separate features and labels again
    features_batch = {k: batch[k] for k in feature_keys}
    labels_batch = {k: batch[k] for k in label_keys}

    return features_batch, labels_batch

  return input_fn


def write_hparams(hparams_dict, path):
  """
  Writes hyperparameter values to a file.

  Args:
    hparams_dict: The dictionary of hyperparameters
    path: Absolute path to write to
  """
  out = "\n".join(
      ["{}={}".format(k, v) for k, v in sorted(hparams_dict.items())])
  with gfile.GFile(path, "w") as file:
    file.write(out)


def read_hparams(path):
  """
  Reads hyperparameters into a string that can be used with a
  HParamsParser.

  Args:
    path: Absolute path to the file to read from
  """
  with gfile.GFile(path, "r") as file:
    lines = file.readlines()
  return ",".join(lines)
