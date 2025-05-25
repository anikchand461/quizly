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

# Load Gemini API key from .env
load_dotenv()
GENAI_API_KEY = os.getenv("GENAI_API_KEY")
genai.configure(api_key=GENAI_API_KEY)

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates directory
templates = Jinja2Templates(directory="templates")

# Store quiz state in memory (not suitable for production)
quiz_state = {
    "questions": [],
    "correct_answers": [],
    "current_index": 0,
    "score": 0
}

# --------------- Pydantic models for internal use ---------------
class Question(BaseModel):
    question: str
    options: List[str]
    correct_answer: str

# --------------- Gemini API & parsing ---------------
def generate_mcqs(topics: List[str], num_questions: int):
    prompt = f"""Generate {num_questions} multiple choice questions (MCQs) on the topics: {', '.join(topics)}.
Each question must have 4 options labeled a., b., c., d. and mention the correct answer clearly as 'Answer: <option letter>'.
Format:
Q1: <question>
a. <option1>
b. <option2>
c. <option3>
d. <option4>
Answer: <a/b/c/d>
"""
    model = genai.GenerativeModel("gemini-2.5-flash-preview-05-20")
    response = model.generate_content(prompt)
    return parse_questions(response.text)

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
                "text": question,  # Match template field name
                "options": options,
                "correct_answer": correct_answer
            })
    return mcqs

# --------------- Routes ---------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    # Reset quiz state if action=reset
    if request.query_params.get("action") == "reset":
        quiz_state["questions"] = []
        quiz_state["correct_answers"] = []
        quiz_state["current_index"] = 0
        quiz_state["score"] = 0
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "questions": quiz_state["questions"],
            "current_index": quiz_state["current_index"],
            "score": quiz_state["score"],
            "topics": "",
            "num_questions": 5,
            "error": None
        }
    )

@app.post("/", response_class=HTMLResponse)
async def generate_quiz(request: Request, topics: str = Form(...), num_questions: int = Form(...)):
    topic_list = [t.strip() for t in topics.split(",") if t.strip()]
    if not topic_list or num_questions < 5 or num_questions > 100:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "questions": [],
                "current_index": 0,
                "score": 0,
                "topics": topics,
                "num_questions": num_questions,
                "error": "Please provide valid topics and a number of questions between 5 and 100."
            }
        )

    # Generate questions
    try:
        questions = generate_mcqs(topic_list, num_questions)
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
                    "error": "Failed to generate questions. Try again."
                }
            )

        # Update quiz state
        quiz_state["questions"] = questions
        quiz_state["correct_answers"] = [q["correct_answer"] for q in questions]
        quiz_state["current_index"] = 0
        quiz_state["score"] = 0

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "questions": quiz_state["questions"],
                "current_index": quiz_state["current_index"],
                "score": quiz_state["score"],
                "topics": topics,
                "num_questions": num_questions,
                "error": None
            }
        )
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
                "error": f"Error generating quiz: {str(e)}"
            }
        )

@app.post("/submit_answer", response_class=JSONResponse)
async def submit_answer(answer: str = Form(...)):
    if not quiz_state["questions"] or quiz_state["current_index"] >= len(quiz_state["questions"]):
        return {"error": "No active quiz or quiz completed"}

    current_question = quiz_state["questions"][quiz_state["current_index"]]
    is_correct = answer == current_question["correct_answer"]
    if is_correct:
        quiz_state["score"] += 1
    quiz_state["current_index"] += 1

    return {
        "is_correct": is_correct,
        "correct_answer": current_question["correct_answer"],
        "score": quiz_state["score"],
        "current_index": quiz_state["current_index"]
    }