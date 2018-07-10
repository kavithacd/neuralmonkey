from typing import List, Optional

import numpy as np
import tensorflow as tf
from typeguard import check_argument_types

# pylint: disable=protected-access
from neuralmonkey.encoders.recurrent import (
    RNNSpecTuple, _make_rnn_spec, _make_rnn_cell)
# pylint: enable=protected-access
from neuralmonkey.model.model_part import ModelPart, FeedDict, InitializerSpecs
from neuralmonkey.model.stateful import TemporalStatefulWithOutput
from neuralmonkey.logging import log
from neuralmonkey.nn.utils import dropout
from neuralmonkey.dataset import Dataset


# pylint: disable=too-many-instance-attributes
class RawRNNEncoder(ModelPart, TemporalStatefulWithOutput):
    """A raw RNN encoder that gets input as a tensor."""

    # pylint: disable=too-many-arguments,too-many-locals
    def __init__(self,
                 name: str,
                 data_id: str,
                 input_size: int,
                 rnn_layers: List[RNNSpecTuple],
                 max_input_len: Optional[int] = None,
                 dropout_keep_prob: float = 1.0,
                 save_checkpoint: Optional[str] = None,
                 load_checkpoint: Optional[str] = None,
                 initializers: InitializerSpecs = None) -> None:
        """Create a new instance of the encoder.

        Arguments:
            data_id: Identifier of the data series fed to this encoder
            name: An unique identifier for this encoder
            rnn_layers: A list of tuples specifying the size and, optionally,
                the direction ('forward', 'backward' or 'bidirectional')
                and cell type ('GRU' or 'LSTM') of each RNN layer.

        Keyword arguments:
            dropout_keep_prob: The dropout keep probability
                (default 1.0)
        """
        check_argument_types()
        ModelPart.__init__(self, name, save_checkpoint, load_checkpoint,
                           initializers)

        self.data_id = data_id

        self._rnn_layers = [_make_rnn_spec(*r) for r in rnn_layers]
        self.max_input_len = max_input_len
        self.input_size = input_size
        self.dropout_keep_prob = dropout_keep_prob

        log("Initializing RNN encoder, name: '{}'"
            .format(self.name))

        with self.use_scope():
            self.inputs = tf.placeholder(
                tf.float32, [None, None, self.input_size], "encoder_input")
            self._input_lengths = tf.placeholder(
                tf.int32, [None], "encoder_padding_lengths")

            self.states_mask = tf.sequence_mask(
                self._input_lengths, dtype=tf.float32)

            states = self.inputs
            states_reversed = False

            def reverse_states():
                nonlocal states, states_reversed
                states = tf.reverse_sequence(
                    states, self._input_lengths, batch_dim=0, seq_dim=1)
                states_reversed = not states_reversed

            for i, layer in enumerate(self._rnn_layers):
                with tf.variable_scope("rnn_{}_{}".format(i, layer.direction)):
                    if layer.direction == "bidirectional":
                        fw_cell = _make_rnn_cell(layer)
                        bw_cell = _make_rnn_cell(layer)
                        outputs_tup, encoded_tup = (
                            tf.nn.bidirectional_dynamic_rnn(
                                fw_cell, bw_cell, states, self._input_lengths,
                                dtype=tf.float32))

                        if states_reversed:
                            # treat forward as backward and vice versa
                            outputs_tup = tuple(reversed(outputs_tup))
                            encoded_tup = tuple(reversed(encoded_tup))
                            states_reversed = False

                        states = tf.concat(outputs_tup, 2)
                        encoded = tf.concat(encoded_tup, 1)
                    elif layer.direction in ["forward", "backward"]:
                        should_be_reversed = (layer.direction == "backward")
                        if states_reversed != should_be_reversed:
                            reverse_states()

                        cell = _make_rnn_cell(layer)
                        states, encoded = tf.nn.dynamic_rnn(
                            cell, states,
                            sequence_length=self._input_lengths,
                            dtype=tf.float32)
                    else:
                        raise ValueError(
                            "Unknown RNN direction {}".format(layer.direction))

                if i < len(self._rnn_layers) - 1:
                    states = dropout(states, self.dropout_keep_prob,
                                     self.train_mode)

            if states_reversed:
                reverse_states()

            self.hidden_states = states
            self.encoded = encoded

        log("RNN encoder initialized")

    @property
    def output(self) -> tf.Tensor:
        return self.encoded

    @property
    def temporal_states(self) -> tf.Tensor:
        return self.hidden_states

    @property
    def temporal_mask(self) -> tf.Tensor:
        return self.states_mask

    def feed_dict(self, dataset: Dataset, train: bool = False) -> FeedDict:
        """Populate the feed dictionary with the encoder inputs.

        Arguments:
            dataset: The dataset to use
            train: Boolean flag telling whether it is training time
        """
        fd = ModelPart.feed_dict(self, dataset, train)

        series = list(dataset.get_series(self.data_id))
        lengths = []
        inputs = []

        max_len = max(x.shape[0] for x in series)
        if self.max_input_len is not None:
            max_len = min(self.max_input_len, max_len)

        for x in series:
            length = min(max_len, x.shape[0])
            x_padded = np.zeros(shape=(max_len,) + x.shape[1:],
                                dtype=x.dtype)
            x_padded[:length] = x[:length]

            lengths.append(length)
            inputs.append(x_padded)

        fd[self.inputs] = inputs
        fd[self._input_lengths] = lengths

        return fd
