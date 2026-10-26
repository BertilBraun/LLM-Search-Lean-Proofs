"""Fresh scores of a served value model on every benchmark state, through the search's own vLLM scoring path."""

from lean_search.value.benchmark import BenchmarkScores, ValueBenchmark, benchmark_fingerprint
from lean_search.value.estimator import ValueModelEstimator
from lean_search.value.prompts import render_value_prompt


async def score_benchmark(estimator: ValueModelEstimator, benchmark: ValueBenchmark) -> BenchmarkScores:
    """Bin distributions read as A* reads them; a state whose prompt does not fit the server's context gets None."""
    fitting = [
        index
        for index, state in enumerate(benchmark.states)
        if len(
            estimator.tokenizer.encode(render_value_prompt(estimator.tokenizer, state.goals), add_special_tokens=False)
        )
        < estimator.max_model_length
    ]
    scored = await estimator.score_states([benchmark.states[index].goals for index in fitting])
    distributions: list[tuple[float, ...] | None] = [None] * len(benchmark.states)
    for index, probabilities in zip(fitting, scored.states, strict=True):
        distributions[index] = probabilities
    model = estimator.config.adapter or estimator.config.model
    return BenchmarkScores(model, benchmark_fingerprint(benchmark), tuple(distributions))
