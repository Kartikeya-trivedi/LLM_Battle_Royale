import os
import json
import asyncio
from google import genai


# ── Shared constants ─────────────────────────────────────────────────
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "gemma-3-27b-it")
_judge_semaphore = asyncio.Semaphore(5)  # Limit concurrent LLM calls


def get_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")
    return genai.Client(api_key=api_key)


CATEGORY_CRITERIA = {
    "Complex Puzzle": {
        "criteria": [
            "Logical Correctness (30%): Is the solution logically sound and does it arrive at the right answer?",
            "Problem Decomposition (25%): How well did the LLM break down the complex puzzle into manageable steps?",
            "Completeness (25%): Does the response address all parts of the puzzle?",
            "Clarity of Explanation (20%): Is the reasoning clear and easy to follow?",
        ],
    },
    "Math": {
        "criteria": [
            "Mathematical Accuracy (35%): Is the final answer correct?",
            "Step-by-Step Reasoning (25%): Are the intermediate steps shown and correct?",
            "Method Selection (20%): Was an appropriate mathematical approach chosen?",
            "Clarity & Notation (20%): Is the math well-formatted and clearly presented?",
        ],
    },
    "General Knowledge": {
        "criteria": [
            "Accuracy (30%): How factually correct is the response?",
            "Depth of Knowledge (25%): How thorough and detailed is the answer?",
            "Relevance (25%): How well does it address the specific question?",
            "Clarity & Coherence (20%): Is it well-structured and easy to understand?",
        ],
    },
}


async def _fetch_with_retries(client, scoring_prompt: str, max_retries: int = 3):
    """Fetch from Gemini with retries on rate limits. Raises on all failures."""
    last_error = None
    for attempt in range(max_retries):
        try:
            return await client.aio.models.generate_content(
                model=JUDGE_MODEL,
                contents=scoring_prompt,
            )
        except Exception as e:
            last_error = e
            if "429" in str(e) or "quota" in str(e).lower() or "503" in str(e):
                if attempt < max_retries - 1:
                    wait = 2 * (attempt + 1)
                    print(f"[Gemini Judge] Rate limit hit. Retrying in {wait}s...")
                    await asyncio.sleep(wait)
                    continue
            raise e
    # All retries exhausted
    raise last_error or RuntimeError("All Gemini retries exhausted with no response")


def _clean_json_text(text: str) -> str:
    """Strip markdown code fences from Gemini response."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    if text.startswith("json"):
        text = text[4:].strip()
    return text


async def judge_submission(challenge_prompt: str, response_text: str, team_name: str, category: str) -> dict:
    """
    Send submission to Gemini for scoring.
    Returns { "score": 0-100, "reasoning": "one-line explanation" }
    """
    criteria_info = CATEGORY_CRITERIA.get(category, CATEGORY_CRITERIA["General Knowledge"])
    criteria_text = "\n".join(f"- {c}" for c in criteria_info["criteria"])

    scoring_prompt = f"""You are an expert judge for the InferenceX LLM Battle Royale competition.

Round Category: {category}

The following challenge prompt was sent to a team's deployed LLM:
---
{challenge_prompt}
---

Team "{team_name}" LLM responded with:
---
{response_text}
---

Score this response on a scale of 0 to 100 based on these criteria:
{criteria_text}

You MUST respond with ONLY valid JSON in this exact format, no other text:
{{"score": <integer 0-100>, "reasoning": "<one concise sentence explaining the score>"}}"""

    try:
        client = get_client()

        async with _judge_semaphore:
            response = await _fetch_with_retries(client, scoring_prompt)

        text = _clean_json_text(response.text)
        result = json.loads(text)
        score = max(0, min(100, int(result.get("score", 0))))
        reasoning = str(result.get("reasoning", "No reasoning provided"))

        return {"score": score, "reasoning": reasoning}

    except json.JSONDecodeError as e:
        print(f"[Gemini Judge] JSON parse error: {e}. Raw: {text[:200]}")
        return {"score": None, "reasoning": "Judging error: could not parse response"}
    except Exception as e:
        print(f"[Gemini Judge] Error: {e}")
        return {"score": None, "reasoning": f"Judging error: {str(e)[:100]}"}


async def judge_match_submission(
    challenge_prompt: str,
    response_a: str,
    response_b: str,
    team_a_name: str,
    team_b_name: str,
    category: str,
) -> dict:
    """
    Judge BOTH teams' responses in a single Gemini call.
    Returns {"team_a_score": 0-100, "team_b_score": 0-100, "reasoning": "..."}
    """
    scoring_prompt = f"""You are an expert judge for the InferenceX LLM Battle Royale competition.

Round Category: {category}

The following challenge prompt was sent to two competing teams' deployed LLMs:
---
{challenge_prompt}
---

Team A ("{team_a_name}") responded with:
---
{response_a or "[NO RESPONSE RECEIVED]"}
---

Team B ("{team_b_name}") responded with:
---
{response_b or "[NO RESPONSE RECEIVED]"}
---

Score BOTH responses on a scale of 0 to 100 based on these criteria:
- Accuracy (40 points): How factually correct and logically sound is the response?
- Completeness (30 points): Does the response fully address all parts of the question?
- Clarity (20 points): Is the response well-structured, clear, and easy to understand?
- Efficiency/Creativity (10 points): Is the approach elegant, creative, or efficient?

You MUST respond with ONLY valid JSON in this exact format, no markdown, no preamble, no other text:
{{"team_a_score": <integer 0-100>, "team_b_score": <integer 0-100>, "reasoning": "<one concise sentence comparing both responses>"}}"""

    try:
        client = get_client()

        async with _judge_semaphore:
            response = await _fetch_with_retries(client, scoring_prompt)

        text = _clean_json_text(response.text)
        result = json.loads(text)

        team_a_score = max(0, min(100, int(result.get("team_a_score", 0))))
        team_b_score = max(0, min(100, int(result.get("team_b_score", 0))))
        reasoning = str(result.get("reasoning", "No reasoning provided"))

        return {
            "team_a_score": team_a_score,
            "team_b_score": team_b_score,
            "reasoning": reasoning,
        }

    except json.JSONDecodeError as e:
        print(f"[Gemini Judge] JSON parse error: {e}. Raw: {text[:200]}")
        return {"team_a_score": 0, "team_b_score": 0, "reasoning": "Judging error: could not parse response"}
    except Exception as e:
        print(f"[Gemini Judge] Error: {e}")
        return {"team_a_score": 0, "team_b_score": 0, "reasoning": f"Judging error: {str(e)[:100]}"}
