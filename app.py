import os
import re
from typing import List
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
import google.generativeai as genai
from starlette.templating import Jinja2Templates
from fastapi.responses import JSONResponse
import asyncio
from itsdangerous import URLSafeSerializer
from fastapi import Cookie, Response

# Load Gemini API key from .env
load_dotenv()
GENAI_API_KEY = os.getenv("GENAI_API_KEY")
genai.configure(api_key=GENAI_API_KEY)

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates directory
templates = Jinja2Templates(directory="templates")

SECRET_KEY = os.getenv("SECRET_KEY", "supersecret")
serializer = URLSafeSerializer(SECRET_KEY)

# --------------- Pydantic models for internal use ---------------
class Question(BaseModel):
    question: str
    options: List[str]
    correct_answer: str

# --------------- Gemini API & parsing ---------------
async def generate_mcqs(topics: List[str], num_questions: int, difficulty: str):
    prompt = f"""Generate {num_questions} multiple choice questions (MCQs) on the topics: {', '.join(topics)} at {difficulty} difficulty level.
Each question must have 4 options labeled a., b., c., d. and mention the correct answer clearly as 'Answer: <option letter>'.
Format:
Q1: <question>
a. <option1>
b. <option2>
c. <option3>
d. <option4>
Answer: <a/b/c/d>
"""
    def sync_call():
        model = genai.GenerativeModel("gemini-2.5-flash-preview-05-20")
        response = model.generate_content(prompt)
        return response.text

    response_text = await asyncio.to_thread(sync_call)
    return parse_questions(response_text)

def parse_questions(text: str):
    mcqs = []
    blocks = re.split(r"Q\d+:", text)
    for block in blocks[1:]:  # Skip first split (empty or partial)
        lines = block.strip().split("\n")
        if len(lines) < 6:
            continue
        question = lines[0].strip()
        options = [line[2:].strip() for line in lines[1:5]]
        answer_line = next((line for line in lines if line.lower().startswith("answer")), "")
        answer_letter = answer_line.strip()[-1].lower()
        answer_index = {"a": 0, "b": 1, "c": 2, "d": 3}.get(answer_letter)
        if answer_index is not None and 0 <= answer_index < len(options):
            correct_answer = options[answer_index]
            mcqs.append({
                "text": question,
                "options": options,
                "correct_answer": correct_answer
            })
    return mcqs

# Update get_quiz_state and set_quiz_state to store user answers
def get_quiz_state(cookie: str = None):
    if cookie:
        try:
            return serializer.loads(cookie)
        except Exception:
            pass
    return {
        "questions": [],
        "correct_answers": [],
        "user_answers": [],
        "current_index": 0,
        "score": 0
    }

def set_quiz_state(response: Response, state: dict):
    cookie_val = serializer.dumps(state)
    response.set_cookie("quiz_state", cookie_val, httponly=True, max_age=3600)

# --------------- Routes ---------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    quiz_state = get_quiz_state(request.cookies.get("quiz_state"))
    # Reset quiz state if action=reset
    if request.query_params.get("action") == "reset":
        quiz_state = {
            "questions": [],
            "correct_answers": [],
            "current_index": 0,
            "score": 0
        }
        response = templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "questions": [],
                "current_index": 0,
                "score": 0,
                "topics": "",
                "num_questions": 5,
                "difficulty": "Medium",
                "error": None
            }
        )
        set_quiz_state(response, quiz_state)
        return response

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "questions": quiz_state["questions"],
            "current_index": quiz_state["current_index"],
            "score": quiz_state["score"],
            "topics": "",
            "num_questions": 5,
            "difficulty": "Medium",
            "error": None
        }
    )

@app.post("/", response_class=HTMLResponse)
async def generate_quiz(request: Request, topics: str = Form(...), num_questions: int = Form(...), difficulty: str = Form(...)):
    topic_list = [t.strip() for t in topics.split(",") if t.strip()]
    if not topic_list or num_questions < 5 or num_questions > 100 or difficulty not in ["Easy", "Medium", "Hard"]:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "questions": [],
                "current_index": 0,
                "score": 0,
                "topics": topics,
                "num_questions": num_questions,
                "difficulty": difficulty,
                "error": "Please provide valid topics, a number of questions between 5 and 100, and a valid difficulty level."
            }
        )

    try:
        questions = await generate_mcqs(topic_list, num_questions, difficulty)
        if not questions:
            return templates.TemplateResponse(
                "index.html",
                {
                    "request": request,
                    "questions": [],
                    "current_index": 0,
                    "score": 0,
                    "topics": topics,
                    "num_questions": num_questions,
                    "difficulty": difficulty,
                    "error": "Failed to generate questions. Try again."
                }
            )

        quiz_state = {
            "questions": questions,
            "correct_answers": [q["correct_answer"] for q in questions],
            "current_index": 0,
            "score": 0
        }

        response = templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "questions": questions,
                "current_index": 0,
                "score": 0,
                "topics": topics,
                "num_questions": num_questions,
                "difficulty": difficulty,
                "error": None
            }
        )
        set_quiz_state(response, quiz_state)

        return response
    except Exception as e:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "questions": [],
                "current_index": 0,
                "score": 0,
                "topics": topics,
                "num_questions": num_questions,
                "difficulty": difficulty,
                "error": f"Error generating quiz: {str(e)}"
            }
        )

@app.post("/submit_answer", response_class=JSONResponse)
async def submit_answer(request: Request, answer: str = Form(...)):
    quiz_state = get_quiz_state(request.cookies.get("quiz_state"))
    if not quiz_state["questions"] or quiz_state["current_index"] >= len(quiz_state["questions"]):
        return JSONResponse({"error": "No active quiz or quiz completed"})

    current_question = quiz_state["questions"][quiz_state["current_index"]]
    is_correct = answer == current_question["correct_answer"]
    if is_correct:
        quiz_state["score"] += 1

    if "user_answers" not in quiz_state:
        quiz_state["user_answers"] = []
    quiz_state["user_answers"].append(answer)

    quiz_state["current_index"] += 1

    response = JSONResponse({
        "is_correct": is_correct,
        "correct_answer": current_question["correct_answer"],
        "score": quiz_state["score"],
        "current_index": quiz_state["current_index"]
    })
    set_quiz_state(response, quiz_state)
    return response

@app.get("/review/{question_index}", response_class=HTMLResponse)
async def review_question(request: Request, question_index: int):
    quiz_state = get_quiz_state(request.cookies.get("quiz_state"))
    questions = quiz_state.get("questions", [])
    user_answers = quiz_state.get("user_answers", [])
    if question_index < 0 or question_index >= len(questions):
        return HTMLResponse("Invalid question index", status_code=404)
    question = questions[question_index]
    user_answer = user_answers[question_index] if question_index < len(user_answers) else None
    correct_answer = question["correct_answer"]

    reason = await explain_answer(question["text"], question["options"], correct_answer, user_answer)

    return templates.TemplateResponse(
        "review.html",
        {
            "request": request,
            "question": question,
            "user_answer": user_answer,
            "correct_answer": correct_answer,
            "reason": reason,
            "question_index": question_index,
        }
    )

async def explain_answer(question_text, options, correct_answer, user_answer):
    if user_answer == correct_answer:
        return "Your answer is correct. Well done!"
    prompt = f"""Question: {question_text}
Options: {options}
Correct Answer: {correct_answer}
User's Answer: {user_answer}
Explain why the correct answer is right and why the user's answer is incorrect."""
    def sync_call():
        model = genai.GenerativeModel("gemini-2.5-flash-preview-05-20")
        response = model.generate_content(prompt)
        return response.text
    try:
        reason = await asyncio.to_thread(sync_call)
        return reason
    except Exception:
        return "Could not generate explanation at this time."

@app.get("/review_all", response_class=HTMLResponse)
async def review_all(request: Request):
    quiz_state = get_quiz_state(request.cookies.get("quiz_state"))
    questions = quiz_state.get("questions", [])
    user_answers = quiz_state.get("user_answers", [])
    explanations = []
    option_explanations = []

    async def gemini_option_explanations(question):
        prompt = f"""Question: {question['text']}
Options: {question['options']}
Correct Answer: {question['correct_answer']}
For each option, explain in 1-2 sentences why it is correct or incorrect in the context of the question. Respond in JSON as:
{{
  "option1": "explanation1",
  "option2": "explanation2",
  ...
}}
Use the option text as the key.
"""
        def sync_call():
            model = genai.GenerativeModel("gemini-2.5-flash-preview-05-20")
            response = model.generate_content(prompt)
            return response.text
        try:
            result = await asyncio.to_thread(sync_call)
            import json
            start = result.find('{')
            end = result.rfind('}') + 1
            json_str = result[start:end]
            return json.loads(json_str)
        except Exception:
            return {opt: "No explanation available." for opt in question["options"]}

    async def gemini_question_explanation(question, user_answer):
        prompt = f"""Question: {question['text']}
Options: {question['options']}
Correct Answer: {question['correct_answer']}
User's Answer: {user_answer}
Explain in 2-3 sentences why the correct answer is right and why the user's answer is incorrect."""
        def sync_call():
            model = genai.GenerativeModel("gemini-2.5-flash-preview-05-20")
            response = model.generate_content(prompt)
            return response.text
        try:
            return await asyncio.to_thread(sync_call)
        except Exception:
            return "Could not generate explanation at this time."

    option_expls = await asyncio.gather(*[gemini_option_explanations(q) for q in questions])
    question_expls = await asyncio.gather(*[
        gemini_question_explanation(q, user_answers[idx] if idx < len(user_answers) else None)
        for idx, q in enumerate(questions)
    ])

    option_explanations = option_expls
    explanations = question_expls

    return templates.TemplateResponse(
        "review_all.html",
        {
            "request": request,
            "questions": questions,
            "user_answers": user_answers,
            "explanations": explanations,
            "option_explanations": option_explanations,
        }
    )