"""ReProver's dense retriever encoder: ByT5 encoder states, masked mean pooling, unit norm."""

from collections.abc import Sequence

import torch
import torch.nn.functional as functional
import transformers

from lean_search.retrieval.config import DEFAULT_RETRIEVER

# ReProver's retriever was trained with `max_seq_len: 1024` (bytes, including the end-of-sequence token).
MAX_LENGTH = 1024
PAD_ID = 0
END_OF_SEQUENCE_ID = 1
BYTE_OFFSET = 3


def byte_token_ids(text: str, max_length: int = MAX_LENGTH) -> list[int]:
    """ByT5's tokenization: one id per UTF-8 byte, truncated, then the end-of-sequence token."""
    return [byte + BYTE_OFFSET for byte in text.encode("utf-8")[: max_length - 1]] + [END_OF_SEQUENCE_ID]


def length_batches(lengths: Sequence[int], max_batch_tokens: int) -> list[list[int]]:
    """Indices grouped longest first so that each batch's padded size stays within `max_batch_tokens`."""
    order = sorted(range(len(lengths)), key=lambda index: -lengths[index])
    batches: list[list[int]] = []
    for index in order:
        if batches and lengths[batches[-1][0]] * (len(batches[-1]) + 1) <= max_batch_tokens:
            batches[-1].append(index)
        else:
            batches.append([index])
    return batches


class TextEncoder:
    def __init__(
        self,
        model: str = DEFAULT_RETRIEVER,
        device: str = "cpu",
        dtype: torch.dtype = torch.float32,
        max_length: int = MAX_LENGTH,
    ) -> None:
        self.device = torch.device(device)
        self.max_length = max_length
        self.model = transformers.T5EncoderModel.from_pretrained(model, dtype=dtype).to(self.device).eval()

    @property
    def dimension(self) -> int:
        return self.model.config.d_model

    @torch.no_grad()
    def encode(self, texts: Sequence[str], max_batch_tokens: int = 32_768) -> torch.Tensor:
        """Unit-norm float32 embeddings on the encoder's device, one row per text in order."""
        token_ids = [byte_token_ids(text, self.max_length) for text in texts]
        embeddings = torch.empty((len(texts), self.dimension), dtype=torch.float32, device=self.device)
        for batch in length_batches([len(ids) for ids in token_ids], max_batch_tokens):
            width = len(token_ids[batch[0]])
            input_ids = torch.full((len(batch), width), PAD_ID, dtype=torch.long)
            attention_mask = torch.zeros((len(batch), width), dtype=torch.long)
            for row, index in enumerate(batch):
                input_ids[row, : len(token_ids[index])] = torch.tensor(token_ids[index])
                attention_mask[row, : len(token_ids[index])] = 1
            input_ids = input_ids.to(self.device)
            attention_mask = attention_mask.to(self.device)
            hidden = self.model(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state.float()
            mask = attention_mask.unsqueeze(2).float()
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1)
            embeddings[torch.tensor(batch, device=self.device)] = functional.normalize(pooled, dim=1)
        return embeddings
