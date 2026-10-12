"""Many examples packed into one row; varlen kernels keep them independent in both Qwen3.5 layer types."""

import functools
import itertools
import random
from collections.abc import Callable, Sequence

import torch
import transformers
from fla.modules.convolution import causal_conv1d
from torch.nn.attention.varlen import varlen_attn
from transformers.integrations.sdpa_attention import sdpa_attention_forward
from transformers.masking_utils import AttentionMaskInterface, sdpa_mask
from transformers.models.qwen3_5 import modeling_qwen3_5

PACKED_ATTENTION = "lean_search_packed"
# Every layer gets the same mapping, so no padding mask is built: the sequence boundaries replace it.
NO_MASKS = {"full_attention": None, "linear_attention": None}


def packed_micro_batches(lengths: Sequence[int], max_tokens: int, generator: random.Random) -> list[tuple[int, ...]]:
    """Shuffled examples filled in order into micro-batches of at most max_tokens tokens (or one longer example)."""
    order = list(range(len(lengths)))
    generator.shuffle(order)
    micro_batches: list[tuple[int, ...]] = []
    current: list[int] = []
    tokens = 0
    for index in order:
        if current and tokens + lengths[index] > max_tokens:
            micro_batches.append(tuple(current))
            current, tokens = [], 0
        current.append(index)
        tokens += lengths[index]
    if current:
        micro_batches.append(tuple(current))
    return micro_batches


def sequence_starts(lengths: Sequence[int]) -> tuple[int, ...]:
    return tuple(itertools.accumulate(lengths, initial=0))


def packed_positions(lengths: Sequence[int]) -> torch.Tensor:
    return torch.cat([torch.arange(length) for length in lengths]).unsqueeze(0)


def packed_hidden_states(
    model: torch.nn.Module, input_ids: torch.Tensor, position_ids: torch.Tensor, starts: Sequence[int]
) -> torch.Tensor:
    """The last hidden states of a packed row; `model` is the causal model's backbone (`causal_model.model`)."""
    starts_on_device = torch.tensor(starts, dtype=torch.int32, device=input_ids.device)
    max_length = max(end - start for start, end in itertools.pairwise(starts))
    return model(
        input_ids=input_ids,
        position_ids=position_ids,
        attention_mask=NO_MASKS,
        use_cache=False,
        cu_seq_lens_q=starts_on_device,
        cu_seq_lens_k=starts_on_device,
        max_length_q=max_length,
        max_length_k=max_length,
        cu_seqlens_cpu=torch.tensor(starts, dtype=torch.int64),
    ).last_hidden_state


@functools.cache
def register_packed_kernels() -> None:
    """Routes packed rows to varlen attention and to FLA's varlen convolution; other inputs keep their kernels."""
    transformers.AttentionInterface.register(PACKED_ATTENTION, packed_attention)
    AttentionMaskInterface.register(PACKED_ATTENTION, sdpa_mask)
    modeling_qwen3_5.causal_conv1d_fn = functools.partial(packed_convolution, modeling_qwen3_5.causal_conv1d_fn)


def enable_packed_sequences(model: transformers.PreTrainedModel) -> None:
    register_packed_kernels()
    model.set_attn_implementation(PACKED_ATTENTION)


def packed_attention(
    module: torch.nn.Module,
    query: torch.Tensor,
    key: torch.Tensor,
    value: torch.Tensor,
    attention_mask: torch.Tensor | None,
    scaling: float | None = None,
    dropout: float = 0.0,
    **kwargs: object,
) -> tuple[torch.Tensor, None]:
    starts = kwargs.get("cu_seq_lens_q")
    if starts is None:
        return sdpa_attention_forward(
            module, query, key, value, attention_mask, scaling=scaling, dropout=dropout, **kwargs
        )
    # One packed row: [1, heads, tokens, dimension] in, [1, tokens, heads, dimension] out.
    output = varlen_attn(
        query[0].transpose(0, 1),
        key[0].transpose(0, 1),
        value[0].transpose(0, 1),
        starts,
        starts,
        kwargs["max_length_q"],
        kwargs["max_length_k"],
        scale=scaling,
        window_size=(-1, 0),
        enable_gqa=True,
    )
    return output.unsqueeze(0), None


def packed_convolution(
    convolution: Callable[..., torch.Tensor],
    hidden_states: torch.Tensor,
    weight: torch.Tensor,
    bias: torch.Tensor | None = None,
    activation: str | None = None,
    **kwargs: object,
) -> torch.Tensor:
    starts = kwargs.get("cu_seq_lens_q")
    if starts is None:
        return convolution(hidden_states, weight, bias, activation=activation, **kwargs)
    # transformers passes [batch, channels, tokens]; FLA restarts the causal window at every sequence start.
    output, _ = causal_conv1d(
        hidden_states.transpose(1, 2),
        weight,
        bias,
        activation=activation,
        cu_seqlens=starts,
        cu_seqlens_cpu=kwargs["cu_seqlens_cpu"],
    )
    return output.transpose(1, 2)
