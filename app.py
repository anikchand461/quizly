import os
import re
from typing import List
from flask import Flask, request, render_template_string, session, jsonify
from dotenv import load_dotenv
import google.generativeai as genai
import logging
import json

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Required for session management

# Load environment variables
try:
    load_dotenv()
    GENAI_API_KEY = os.getenv("GENAI_API_KEY")
    if not GENAI_API_KEY:
        raise ValueError("GENAI_API_KEY not found in .env file")
    genai.configure(api_key=GENAI_API_KEY)
    logger.info("Gemini API configured successfully")
except Exception as e:
    logger.error(f"Failed to configure Gemini API: {e}")
    raise

def generate_questions(topics: List[str], num_questions: int) -> List[dict]:
    """Generate multiple-choice questions using Gemini API."""
    prompt = (
        f"Generate {num_questions} multiple-choice questions on the topics: {', '.join(topics)}. "
        "Each question should have 4 options (a, b, c, d) and specify the correct answer. "
        "Format each question as:\n"
        "Question: <question text>\n"
        "a. <option1>\n"
        "b. <option2>\n"
        "c. <option3>\n"
        "d. <option4>\n"
        "Correct Answer: <option letter>\n"
    )
    try:
        model = genai.GenerativeModel("gemini-2.5-flash-preview-05-20")
        response = model.generate_content(prompt)
        return parse_response(response.text)
    except Exception as e:
        logger.error(f"Error generating questions: {e}")
        return []

def parse_response(text: str) -> List[dict]:
    """Parse Gemini API response into a list of question dictionaries."""
    questions = []
    blocks = re.split(r"Question:", text)[1:]  # Skip anything before first question
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 6:
            continue
        question_text = lines[0].strip()
        options = [line[2:].strip() for line in lines[1:5] if line.strip().startswith(('a.', 'b.', 'c.', 'd.'))]
        correct_line = next((line for line in lines if line.lower().startswith("correct answer:")), None)
        if not correct_line or len(options) != 4:
            continue
        correct_letter = correct_line.split(":")[-1].strip().lower()
        letter_to_index = {"a": 0, "b": 1, "c": 2, "d": 3}
        if correct_letter not in letter_to_index:
            continue
        correct_answer = options[letter_to_index[correct_letter]]
        questions.append({
            "text": question_text,
            "options": options,
            "correct_answer": correct_answer
        })
    return questions

@app.route("/", methods=["GET", "POST"])
def quiz_page():
    error = None

    if request.method == "POST":
        topics = request.form.get("topics", "").strip()
        num_questions = request.form.get("num_questions", type=int, default=5)

        # Validate inputs
        if not topics:
            error = "Please enter at least one topic."
        elif num_questions < 5 or num_questions > 100:
            error = "Number of questions must be between 5 and 100."
        else:
            topic_list = [t.strip() for t in topics.split(",") if t.strip()]
            questions = generate_questions(topic_list, num_questions)
            if not questions:
                error = "Failed to generate questions. Please try again."
            else:
                # Store questions and reset state in session
                session['questions'] = questions
                session['current_index'] = 0
                session['score'] = 0
                logger.info(f"Generated {len(questions)} questions for topics: {topics}")

    # Handle reset
    if request.args.get("action") == "reset":
        session.pop('questions', None)
        session.pop('current_index', None)
        session.pop('score', None)
        logger.info("Quiz state reset")

    # Get state from session
    questions = session.get('questions', [])
    current_index = session.get('current_index', 0)
    score = session.get('score', 0)

    return render_template_string(
        open("templates/index.html").read(),
        questions=json.dumps(questions),  # Serialize to JSON for JavaScript
        current_index=current_index,
        score=score,
        error=error
    )

@app.route("/submit_answer", methods=["POST"])
def submit_answer():
    """Handle answer submission."""
    if 'questions' not in session or 'current_index' not in session:
        return jsonify({"error": "No active quiz session"}), 400

    questions = session['questions']
    current_index = session['current_index']
    user_answer = request.form.get("answer")

    if not user_answer:
        return jsonify({"error": "No answer selected"}), 400

    if current_index >= len(questions):
        return jsonify({"error": "Quiz completed"}), 400

    q = questions[current_index]
    is_correct = user_answer == q['correct_answer']
    if is_correct:
        session['score'] = session.get('score', 0) + 1

    session['current_index'] = current_index + 1
    session.modified = True  # Ensure session updates

    return jsonify({
        "is_correct": is_correct,
        "correct_answer": q['correct_answer'],
        "current_index": session['current_index'],
        "score": session['score'],
        "quiz_completed": session['current_index'] >= len(questions)
    })

if __name__ == "__main__":
    app.run(debug=True)