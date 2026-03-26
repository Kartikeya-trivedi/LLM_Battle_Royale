# Predefined questions for each bracket round and sub-round.
# Sub-rounds: 1 = Complex Puzzle, 2 = Math, 3 = General Knowledge (Comprehension)

ROUND_QUESTIONS = {
    1: {
        1: (
            "Explain why a neural network with no activation function is just a linear regression, "
            "no matter how many layers it has."
        ),
        2: (
            "A train travels 120 km at 60 km/h and returns at 40 km/h. "
            "What is the average speed for the whole journey?"
        ),
        3: (
            '"The best investment you can make is in yourself." '
            "Explain what this means and give a real world example."
        ),
    },
    2: {
        1: (
            "A company stores user passwords as plain MD5 hashes. "
            "List every problem with this and explain what they should do instead."
        ),
        2: (
            "If you fold a paper in half 42 times, the thickness would exceed the distance from "
            "Earth to the Moon. The paper is 0.1mm thick. Verify this claim."
        ),
        3: (
            "Read this and summarise in 3 bullet points — "
            '"Compounding is the eighth wonder of the world. He who understands it, earns it; '
            "he who doesn't, pays it. Most people overestimate what they can do in a year and "
            'underestimate what they can do in a decade."'
        ),
    },
    3: {
        1: (
            "Explain the difference between latency and throughput in an LLM inference system. "
            "If you had to serve 1000 users simultaneously, which would you optimise for and why?"
        ),
        2: (
            "You have a 3-litre jug and a 5-litre jug. No markings. "
            "How do you measure exactly 4 litres?"
        ),
        3: (
            '"In the middle of difficulty lies opportunity." — Einstein. '
            "A startup just lost its biggest client. Write a 5-sentence internal memo "
            "reframing this as an opportunity."
        ),
    },
    4: {
        1: (
            "A REST API is returning correct results but response time jumps from 200ms to "
            "8 seconds under load. Walk through every possible cause and how you'd diagnose each one."
        ),
        2: (
            "You have 12 balls, one is slightly heavier. You have a balance scale and only "
            "3 weighings. How do you find the heavy ball?"
        ),
        3: (
            "Explain the trolley problem to a 10-year-old, then explain it to a philosophy "
            "professor. Two separate answers."
        ),
    },
    5: {
        1: (
            "You are deploying a 7B parameter LLM on a server with 16GB VRAM. The model in FP16 "
            "needs 14GB. A user wants to run it with a 4096 token context window. Will it fit? "
            "What would you do to make it production-safe?"
        ),
        2: (
            "A disease affects 1 in 1000 people. A test for it is 99% accurate. You test positive. "
            "What is the actual probability you have the disease? Show full working."
        ),
        3: (
            '"Privacy is not about having something to hide. It is about having the power to '
            'choose what you share." Write a 150-word argument for this statement, then write '
            "a 150-word counterargument."
        ),
    },
    6: {
        1: (
            "Design the full architecture of a production LLM API that serves 10,000 requests "
            "per day. Cover model choice, quantization strategy, cloud vs local tradeoff, rate "
            "limiting, fallback handling, and estimated monthly cost. Be specific."
        ),
        2: (
            "You are running a model that costs $0.002 per 1000 tokens. Your app averages 800 "
            "tokens per request. You get 50,000 requests per day. Calculate monthly cost. Then "
            "calculate how much it drops if you switch to a quantized model that is 60% cheaper "
            "but handles only 80% of queries correctly, requiring the rest to fall back to the "
            "original model."
        ),
        3: (
            '"Technology is neither good nor bad, nor is it neutral." — Melvin Kranzberg. '
            "Apply this specifically to large language models. Give one example where an LLM "
            "created clear value and one where it caused clear harm. Then give your own stance "
            "in 3 sentences."
        ),
    },
}


def get_questions_for_round(round_num: int) -> dict:
    """Get questions for a given round, with a fallback for rounds beyond 6."""
    if round_num in ROUND_QUESTIONS:
        return ROUND_QUESTIONS[round_num]
    # Fallback: generate generic questions for rounds beyond what's defined
    return {
        1: f"Round {round_num} Complex Puzzle: Design a creative algorithmic solution to a real-world optimization problem of your choosing. Explain your approach step by step.",
        2: f"Round {round_num} Math: A factory produces items with a 2% defect rate. If you sample 500 items, what is the probability of finding more than 15 defective items? Show your work using appropriate statistical methods.",
        3: f"Round {round_num} General Knowledge: Compare and contrast two major technological breakthroughs of the 21st century. Discuss their societal impact, ethical implications, and future potential.",
    }
