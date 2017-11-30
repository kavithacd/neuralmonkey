from typing import Dict, List

import tensorflow as tf

from neuralmonkey.decoders.decoder import Decoder
from neuralmonkey.model.model_part import ModelPart
from neuralmonkey.runners.base_runner import (BaseRunner, Executable,
                                              ExecutionResult, NextExecute)


class WordAlignmentRunner(BaseRunner):

    def __init__(self,
                 output_series: str,
                 encoder: ModelPart,
                 decoder: Decoder) -> None:
        super(WordAlignmentRunner, self).__init__(output_series, decoder)

        self._encoder = encoder

    def get_executable(self,
                       compute_losses: bool = False,
                       summaries: bool = True,
                       num_sessions: int = 1) -> WordAlignmentRunnerExecutable:
        att_object = self._decoder.get_attention_object(self._encoder,
                                                        train_mode=False)
        alignment = tf.transpose(
            tf.stack(att_object.attentions_in_time), perm=[1, 2, 0])
        fetches = {"alignment": alignment}

        return WordAlignmentRunnerExecutable(self.all_coders,
                                             fetches,
                                             num_sessions)

    @property
    def loss_names(self) -> List[str]:
        return []


class WordAlignmentRunnerExecutable(Executable):

    def __init__(self,
                 all_coders: Set[ModelPart],
                 fetches: FeedDict,
                 num_sessions: int) -> None:
        self.all_coders = all_coders
        self._fetches = fetches
        self._num_sessions = num_sessions

        self.result = None  # type: Optional[ExecutionResult]

    def next_to_execute(self) -> NextExecute:
        """Get the feedables and tensors to run."""
        return (self.all_coders,
                self._fetches,
                [{} for _ in range(self._num_sessions)])

    def collect_results(self, results: List[Dict]) -> None:
        self.result = ExecutionResult(
            outputs=results[0]["alignment"],
            losses=[],
            scalar_summaries=None,
            histogram_summaries=None,
            image_summaries=None)
