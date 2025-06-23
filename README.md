Quizly - AI-Powered Quiz Generation Application

Quizly is a state-of-the-art quiz generation application that utilizes the Google Gemini Generative AI API to create sophisticated, context-aware multiple-choice questions based on user-specified topics. Developed with a robust FastAPI backend and a clean, responsive HTML/CSS/JavaScript frontend, Quizly delivers a seamless user experience for learners and educators alike.

Features
	•	AI-driven generation of dynamic, multiple-choice questions across a wide range of topics
	•	Provides instant feedback and assessment for questions
	•	Integrates with the Google Gemini API for advanced, context-rich question generation
	•	User-friendly, clean, and minimalist interface

Tech Stack

Layer	Technology
Backend	FastAPI
Frontend	HTML, CSS, JavaScript
AI Model	Google Gemini via API

Installation
	1.	Clone the Repository:

git clone https://github.com/your-username/Quizly.git
cd Quizly


	2.	Install Dependencies:

pip install -r requirements.txt


	3.	Setup Environment Variables:
Create a .env file with your Gemini API key:

GENAI_API_KEY=your_google_gemini_api_key


	4.	Run the Application Locally:

uvicorn main:app --reload



Deployment
	•	Render: Set the start command as unicorn main:app --reload.
	•	Railway: Configure the app and obtain the deployment URL from the Railway dashboard.

Usage
	1.	Open the app in a browser.
	2.	Enter desired topics (comma-separated).
	3.	Choose the number of questions.
	4.	Click “Generate Quiz” to begin.

Contributing

We welcome contributions. To propose changes or enhancements, open an issue for discussion first. All PRs must adhere to project coding and documentation standards.

License

Distributed under the MIT License.