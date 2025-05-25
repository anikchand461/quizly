# 🎓 Quizly - AI Powered Quiz Generator

**Quizly** is a smart quiz application that uses **Google Gemini** (via the Generative AI API) to generate multiple choice questions based on user-defined topics. It's built with a **FastAPI backend** and a simple **HTML/CSS/JavaScript frontend**.

---

## 🚀 Features

* Generate quizzes dynamically from any topic
* Multiple-choice questions with instant feedback
* AI-powered using Gemini (Google Generative AI)
* Clean, minimal UI for a smooth quiz-taking experience

---

## 🛠️ Tech Stack

| Layer        | Technology            |
| ------------ | --------------------- |
| **Backend**  | FastAPI               |
| **Frontend** | HTML, CSS, JavaScript |
| **AI Model** | Google Gemini via API |

---

## 📦 Installation

1. **Clone the repository**:

```bash
git clone https://github.com/your-username/quizly.git
cd quizly
```

2. **Install dependencies**:

```bash
pip install -r requirements.txt
```

3. **Set up `.env` file**:

```
GENAI_API_KEY=your_google_gemini_api_key
```

4. **Run the application locally**:

```bash
uvicorn main:app --reload
```

---

## 🌐 Deployment

This app can be deployed on platforms like **Render**, **Railway**, or **Vercel**.

* For **Render**: Set the start command as:

```
unicorn main:app --reload
```

* For **Railway**: Visit your project dashboard, find the `https://...railway.app` URL for your deployed app.

---

## 🧪 Usage

1. Open the app in a browser.
2. Enter your topics (comma-separated).
3. Select the number of questions.
4. Click **Generate Quiz** and start answering!

---

## 🙌 Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

---

## 📄 License

[MIT](LICENSE)

---

## 📬 Contact

Made with ❤️ by [Abhiraj Adhikary](https://github.com/abhirajadhikary06) and [Anik Chand](https://github.com/anikchand461)
