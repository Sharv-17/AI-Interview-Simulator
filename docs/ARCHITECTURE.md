# AI Interview Simulator — System Architecture

## 1. Architecture Overview

The AI Interview Simulator follows a modular client-server architecture.

The system consists of:

- Frontend
- Backend API
- Interview Engine
- AI Question Generation
- AI Answer Evaluation
- Voice Processing
- Interview Integrity Module
- Database

The architecture is designed so that both voice and text responses use the same interview and evaluation pipeline.

---

## 2. High-Level Architecture

```text
                         ┌──────────────────────┐
                         │         USER         │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │      FRONTEND        │
                         │   React + Vite       │
                         │                      │
                         │ • Interview Setup    │
                         │ • Interview Screen   │
                         │ • Results            │
                         └──────────┬───────────┘
                                    │
                              REST API / HTTP
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │       BACKEND        │
                         │       FastAPI        │
                         └──────────┬───────────┘
                                    │
             ┌──────────────────────┼──────────────────────┐
             │                      │                      │
             ▼                      ▼                      ▼
    ┌────────────────┐    ┌────────────────┐    ┌────────────────┐
    │ Interview      │    │ AI Evaluation  │    │ Voice          │
    │ Engine         │    │ Engine         │    │ Processing     │
    └───────┬────────┘    └───────┬────────┘    └───────┬────────┘
            │                     │                     │
            └─────────────────────┼─────────────────────┘
                                  │
                                  ▼
                         ┌──────────────────────┐
                         │       DATABASE       │
                         │      PostgreSQL      │
                         └──────────────────────┘

 ``` 
  
## 3. Frontend

The frontend provides the interface through which candidates configure and complete interviews.

Main Components
Interview Setup

The candidate can select:

Job role
Experience level
Interview type
Skills or topics
Number of questions
Interview mode
Interview Screen

The interview screen displays:

Current question
Question number
Countdown timer
Voice recording controls
Text answer input
Submit button
Results

The results screen displays:

Overall score
Technical performance
Answer quality
Communication indicators
Strengths
Weaknesses
Personalized feedback
Interview integrity indicators

## 4. Backend

The backend acts as the central controller of the application.

Responsibilities
Manage interview sessions
Generate questions
Receive candidate answers
Process voice responses
Request AI evaluations
Control adaptive questioning
Calculate performance scores
Store interview data
Communicate with the database
Technology

Python + FastAPI

The backend will also keep sensitive information such as API keys away from the frontend. 

## 5. Interview Engine

The Interview Engine controls the progression of each interview.

It maintains the current interview state and determines what question should be presented next.

Interview Flow
```
START
  ↓
INTERVIEW SETUP
  ↓
GENERATE QUESTION
  ↓
START TIMER
  ↓
WAIT FOR ANSWER
  ↓
ANSWER RECEIVED
  ↓
EVALUATE ANSWER
  ↓
UPDATE PERFORMANCE
  ↓
ADJUST DIFFICULTY
  ↓
GENERATE NEXT QUESTION
  │
  ├── More questions → Repeat
  │
  └── No questions → Final Report
  ```
The Interview Engine is responsible for maintaining the interview state rather than allowing the AI model to control the entire process.

## 6. Adaptive Questioning

Adaptive questioning is the core feature of the system.

Instead of asking a fixed sequence of questions, the system uses the candidate's previous performance to determine the next question.

Example
```
Question 1
    ↓
Strong Answer
    ↓
Increase Difficulty
    ↓
Question 2
    ↓
Weak Answer
    ↓
Identify Weak Topic
    ↓
Targeted Question
```
The evaluation system will provide structured information such as:
```
{
  "technical_score": 8,
  "relevance_score": 9,
  "clarity_score": 7,
  "completeness_score": 8,
  "overall_score": 8,
  "weak_topics": [],
  "recommended_difficulty": "hard"
}
```
The backend will use this information to determine the next question.

The AI can recommend a difficulty level, but the backend will control the final decision.

## 7. AI Question Generation and Answer Evaluation

The AI layer has two primary responsibilities.

Question Generation

The AI receives information such as:

Job role
Experience level
Interview type
Skills
Current difficulty
Previous questions
Previous performance
Weak topics

It then generates an appropriate interview question.

Example:
```
{
  "question": "Explain polymorphism in Python with an example.",
  "topic": "Object-Oriented Programming",
  "difficulty": "medium",
  "type": "technical"
}
```
Answer Evaluation

The candidate's answer is evaluated using:

Technical accuracy
Relevance
Clarity
Completeness
Overall answer quality

The evaluation produces structured results that are passed to the Interview Engine.
```
Question
    +
Candidate Answer
    ↓
AI Evaluation
    ↓
Scores + Feedback + Weak Topics
    ↓
Adaptive Interview Engine
```

## 8. Voice and Text Processing
Both voice and text are core input methods.
**Voice Pipeline**
```
Candidate
    ↓
Microphone
    ↓
Audio Recording
    ↓
Speech-to-Text
    ↓
Transcribed Answer
    ↓
AI Answer Evaluation
```
Voice responses can additionally provide communication indicators such as:

Speaking duration
Speaking rate
Filler words
Long pauses

These are treated as communication indicators and not definitive measurements of confidence or personality.

**Text Pipeline**
```
Candidate
    ↓
Text Input
    ↓
Timer + Integrity Checks
    ↓
Answer Submission
    ↓
AI Evaluation
```
Both input methods eventually enter the same evaluation pipeline:
```
Voice ──→ Speech-to-Text ──┐
                           ├──→ Answer Evaluation
Text ──────────────────────┘
```

## 9. Interview Integrity

The initial version will use a simple integrity system.

Per-Question Timer

Each question has a time limit.

The initial default is:

90 seconds

The timer starts when the question is displayed.

When the timer reaches zero, the answer is automatically submitted.

Different question types may receive different time limits in future versions.

**Copy/Paste Detection**

The system will detect relevant copy and paste events during text-based answers.

These events will be recorded as integrity indicators.

A copy/paste event will not automatically classify a candidate as cheating.

Example:
```
Paste Events: 0
Integrity Status: Normal
```
or:
```
Paste Events: 1
Integrity Status: Review Recommended
```
More advanced integrity mechanisms can be added later if required.

## 10. Database and Data Flow

The database will store information related to users, interviews, questions, answers, scores, and feedback.

Basic Data Structure
```
USER
 │
 └── INTERVIEW
       │
       ├── Configuration
       │
       ├── Question
       │     ├── Answer
       │     ├── Score
       │     └── Feedback
       │
       ├── Question
       │     ├── Answer
       │     ├── Score
       │     └── Feedback
       │
       └── Final Report
```
Complete Data Flow
```
USER
  ↓
Interview Setup
  ↓
Create Interview Session
  ↓
Generate Question
  ↓
Start Timer
  ↓
Candidate Answers
  │
  ├──────────────┐
  │              │
Voice           Text
  │              │
  ↓              ↓
Speech-to-Text   Integrity Checks
  │              │
  └───────┬──────┘
          ↓
    Answer Evaluation
          ↓
    Performance Analysis
          ↓
    Adaptive Decision
          ↓
    Next Question
          │
          └──→ Repeat

After final question
          ↓
    Final Interview Report
```
## 11. Technology Stack

| Component |	Technology |
|-----------|--------------|
| Frontend |	React + Vite |
| Backend |	Python + FastAPI |
| AI	 | LLM API |
| Speech-to-Text |	Speech Recognition API |
| Database |	PostgreSQL |
| Communication |	REST API |
| Version Control | 	Git + GitHub |
| Development |	 VS Code |

The exact AI and speech-to-text providers will be selected during implementation.

## 12. Design Principles
**Modularity**
Each component should have a clear responsibility and should be replaceable where practical.

**Shared Evaluation Pipeline**
Voice and text responses should use the same answer evaluation system after voice is converted to text.

**Backend-Controlled Logic**
The backend controls interview progression and adaptive difficulty. The AI provides evaluation and recommendations but does not independently control the interview.

**Security**
API keys and other sensitive information must never be stored in the frontend or committed to GitHub.

**Incremental Development**
Features will be developed, tested, and committed independently before major integration.

**Extensibility**
The architecture should allow future additions such as:
-Interview history
-Advanced analytics
-Personalized learning recommendations
-Company-specific interviews
-Advanced communication analysis
-Advanced interview integrity mechanisms