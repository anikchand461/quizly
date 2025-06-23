import os
import re
from typing import List
from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, HTTPException, Response, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
import google.generativeai as genai
from starlette.templating import Jinja2Templates
import asyncio
from itsdangerous import URLSafeSerializer
from passlib.context import CryptContext
import uuid
import requests
from tempfile import NamedTemporaryFile
from db import SessionLocal, QuizRequest, User as DBUser
from sqlalchemy.orm import Session

# Load Gemini API key from .env
load_dotenv()
GENAI_API_KEY = os.getenv("GENAI_API_KEY")
genai.configure(api_key=GENAI_API_KEY)

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates directory
templates = Jinja2Templates(directory="templates")

# Secret key for session management
SECRET_KEY = os.getenv("SECRET_KEY", "supersecret")
serializer = URLSafeSerializer(SECRET_KEY)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# In-memory user store (replace with database in production)
users_db = {}

# --------------- Pydantic models ---------------
class Question(BaseModel):
    question: str
    options: List[str]
    correct_answer: str

class User(BaseModel):
    username: str
    password: str

# --------------- Authentication ---------------
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_session_token(username: str):
    return serializer.dumps({"username": username})

def get_user_by_username(db: Session, username: str):
    return db.query(DBUser).filter(DBUser.username == username).first()

def get_current_user(session: str = Cookie(None)):
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        data = serializer.loads(session)
        username = data.get("username")
        db = SessionLocal()
        user = get_user_by_username(db, username)
        db.close()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid session")
        return user  # <-- Return the user object, not username
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid session")

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

# --- OCR Space API Helper ---
def ocr_space_extract(image_file, api_key, language='eng'):
    url = 'https://api.ocr.space/parse/image'
    with NamedTemporaryFile(delete=False, suffix=".jpg") as temp_img:
        temp_img.write(image_file)
        temp_img.flush()
        temp_img.seek(0)
        with open(temp_img.name, 'rb') as f:
            payload = {
                'isOverlayRequired': True,
                'apikey': api_key,
                'language': language,
                'OCREngine': 2,
                'isTable': True,
                'scale': True,
                'detectOrientation': True
            }
            files = {'file': f}
            response = requests.post(url, data=payload, files=files)
            try:
                result = response.json()
            except Exception:
                return ""
            if not isinstance(result, dict):
                return ""
            if result.get("IsErroredOnProcessing"):
                return ""
            parsed_results = result.get("ParsedResults", [])
            if parsed_results:
                return parsed_results[0].get("ParsedText", "")
            return ""

# --------------- Routes ---------------
@app.get("/", response_class=HTMLResponse)
async def login_signup_page(request: Request, session: str = Cookie(None)):
    # If user is already logged in, redirect to quiz page
    if session:
        try:
            get_current_user(session)
            return RedirectResponse(url="/quiz")
        except HTTPException:
            pass  # Invalid session, show login page
    return templates.TemplateResponse(
        "auth.html",
        {
            "request": request,
            "error": None,
            "mode": "login"  # Default to login mode
        }
    )

@app.post("/auth", response_class=HTMLResponse)
async def auth_handler(
    request: Request,
    mode: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    name: str = Form(None)
):
    username = email.strip().lower()
    db = SessionLocal()
    try:
        if mode == "signup":
            if not name or not username or not password:
                return templates.TemplateResponse(
                    "auth.html",
                    {
                        "request": request,
                        "error": "All fields are required for signup.",
                        "mode": "signup"
                    }
                )
            if get_user_by_username(db, username):
                return templates.TemplateResponse(
                    "auth.html",
                    {
                        "request": request,
                        "error": "Email already registered.",
                        "mode": "signup"
                    }
                )
            db_user = DBUser(
                username=username,
                hashed_password=get_password_hash(password),
                email=name
            )
            db.add(db_user)
            db.commit()
            response = RedirectResponse(url="/quiz", status_code=303)
            session_token = create_session_token(username)
            response.set_cookie("session", session_token, httponly=True, max_age=3600)
            return response
        else:  # mode == "login"
            user = get_user_by_username(db, username)
            if not user or not verify_password(password, user.hashed_password):
                return templates.TemplateResponse(
                    "auth.html",
                    {
                        "request": request,
                        "error": "Invalid email or password.",
                        "mode": "login"
                    }
                )
            response = RedirectResponse(url="/quiz", status_code=303)
            session_token = create_session_token(username)
            response.set_cookie("session", session_token, httponly=True, max_age=3600)
            return response
    finally:
        db.close()

@app.get("/logout")
async def logout(response: Response):
    response = RedirectResponse(url="/")
    response.delete_cookie("session")
    response.delete_cookie("quiz_state")
    return response

@app.get("/quiz", response_class=HTMLResponse)
async def quiz_page(request: Request, current_user: str = Depends(get_current_user)):
    quiz_state = get_quiz_state(request.cookies.get("quiz_state"))
    if request.query_params.get("action") == "reset":
        quiz_state = {
            "questions": [],
            "correct_answers": [],
            "user_answers": [],
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
                "error": None,
                "username": current_user.username  # <-- FIXED
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
            "error": None,
            "username": current_user.username,  # <-- FIXED
        }
    )

@app.post("/quiz", response_class=HTMLResponse)
async def generate_quiz(
    request: Request,
    input_type: str = Form(...),
    topics: str = Form(""),
    num_questions: int = Form(...),
    difficulty: str = Form(...),
    pdf_file: UploadFile = File(None),
    image_file: UploadFile = File(None),
    current_user: DBUser = Depends(get_current_user)
):
    content_text = ""
    if input_type == "text":
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
                    "error": "Please provide valid topics, a number of questions between 5 and 100, and a valid difficulty level.",
                    "username": current_user.username
                }
            )
        content_text = ", ".join(topic_list)
    elif input_type == "pdf" and pdf_file is not None:
        import PyPDF2
        from io import BytesIO
        pdf_bytes = await pdf_file.read()
        pdf_reader = PyPDF2.PdfReader(BytesIO(pdf_bytes))
        content_text = ""
        for page in pdf_reader.pages:
            content_text += page.extract_text() or ""
        if not content_text.strip() or num_questions < 5 or num_questions > 100 or difficulty not in ["Easy", "Medium", "Hard"]:
            return templates.TemplateResponse(
                "index.html",
                {
                    "request": request,
                    "questions": [],
                    "current_index": 0,
                    "score": 0,
                    "topics": "",
                    "num_questions": num_questions,
                    "difficulty": difficulty,
                    "error": "Could not extract text from PDF, or invalid question count/difficulty.",
                    "username": current_user.username  # <-- FIXED
                }
            )
    elif input_type == "image" and image_file is not None:
        image_bytes = await image_file.read()
        ocr_api_key = os.getenv("OCR_SPACE_API_KEY")
        content_text = ocr_space_extract(image_bytes, api_key=ocr_api_key, language='eng')
        if not content_text.strip() or num_questions < 5 or num_questions > 100 or difficulty not in ["Easy", "Medium", "Hard"]:
            return templates.TemplateResponse(
                "index.html",
                {
                    "request": request,
                    "questions": [],
                    "current_index": 0,
                    "score": 0,
                    "topics": "",
                    "num_questions": num_questions,
                    "difficulty": difficulty,
                    "error": "Could not extract text from image, or invalid question count/difficulty.",
                    "username": current_user.username 
                }
            )
    else:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "questions": [],
                "current_index": 0,
                "score": 0,
                "topics": "",
                "num_questions": num_questions,
                "difficulty": difficulty,
                "error": "Please provide valid topics, upload a PDF, or upload an image.",
                "username": current_user.username 
            }
        )

    try:
        questions = await generate_mcqs_from_text(content_text, num_questions, difficulty)
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
                    "error": "Failed to generate questions. Try again.",
                    "username": current_user.username 
                }
            )

        quiz_state = {
            "questions": questions,
            "correct_answers": [q["correct_answer"] for q in questions],
            "user_answers": [],
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
                "error": None,
                "username": current_user.username 
            }
        )
        set_quiz_state(response, quiz_state)

        db = SessionLocal()
        user = db.query(DBUser).filter(DBUser.id == current_user.id).first()
        user.generation_count += 1  # Increment generation count
        quiz_request = QuizRequest(
            user_id=user.id,
            input_type=input_type,
            topic=topics,
            num_questions=num_questions,
            difficulty=difficulty
        )
        db.add(quiz_request)
        db.commit()
        db.close()

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
                "error": f"Error generating quiz: {str(e)}",
                "username": current_user.username 
            }
        )

@app.post("/submit_answer", response_class=JSONResponse)
async def submit_answer(
    request: Request,
    answer: str = Form(...),
    current_user: str = Depends(get_current_user)
):
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
async def review_question(
    request: Request,
    question_index: int,
    current_user: str = Depends(get_current_user)
):
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
            "username": current_user.username 
        }
    )

@app.get("/review_all", response_class=HTMLResponse)
async def review_all(request: Request, current_user: str = Depends(get_current_user)):
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
            "username": current_user.username 
        }
    )

async def generate_mcqs_from_text(content_text: str, num_questions: int, difficulty: str):
    prompt = f"""Based on the following content, generate {num_questions} multiple choice questions (MCQs) at {difficulty} difficulty level.
Content:
{content_text}
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

# Example FastAPI route
from fastapi import Request, Depends
from fastapi.responses import HTMLResponse
from starlette.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")

# Example FastAPI route
@app.get("/profile")
def profile(request: Request, current_user: DBUser = Depends(get_current_user)):
    db = SessionLocal()
    quiz_requests = db.query(QuizRequest).filter(QuizRequest.user_id == current_user.id).all()
    db.close()
    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "username": current_user.username,  # Pass username only
            "quiz_requests": quiz_requests
        }
    )

@app.get("/leaderboard", response_class=HTMLResponse)
def leaderboard(request: Request):
    db = SessionLocal()
    users = db.query(DBUser).order_by(DBUser.generation_count.desc()).all()
    db.close()
    return templates.TemplateResponse(
        "leaderboard.html",
        {
            "request": request,
            "users": users
        }
    )