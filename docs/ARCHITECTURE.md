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

## 13. Implementation Status: Competency State (Stage 3.5)

The sections above describe the eventual, aspirational architecture.
This section documents what is actually implemented as of Stage 3.5.

After Stage 3.4's answer evaluation, each interview now maintains an
**estimated competency state** per competency encountered, in
`app/services/competency_state.py`. This is the first piece of the
planned adaptive pipeline:
theta -> H(theta) -> IDI -> DifficultyFit -> QScore


**Only theta (competency state estimation) is implemented.** Shannon
entropy H(theta), IDI, DifficultyFit, and the final QScore are **not**
implemented yet, and no question selection currently uses competency
state — question retrieval still works exactly as in Stage 3.3.

**What theta is:** for each competency, `theta` is an *estimated*
competency level in `[0.0, 1.0]` inferred from observed answer
performance — not an objective measure of the candidate's true
ability. It starts at `theta_initial = 0.5` (neutral) the first time a
competency is encountered (lazy initialization; competencies are never
pre-populated).

**Update formula**, applied after every evaluated answer for that
answer's competency:

theta_new = (1 - alpha) * theta_old + alpha * S


where `S` is the answer's Stage 3.4 `overall_score` normalized from
`[0,10]` to `[0,1]` (`S = overall_score / 10`, clamped), and
`alpha = 0.15` is a fixed research design constant — it is not
configurable and must not be changed without updating this document.

EMA is used so recent performance shifts the estimate while still
being smoothed by prior answers, rather than each new answer either
being ignored or completely overwriting the running estimate.

The competency touched is chosen from the answered question's
metadata, preferring: explicit `competency` field → `subtopic` →
`topic` → a safe fallback label, so a question missing some metadata
never crashes the interview.

Competency state belongs to a single interview session (never shared
globally). It is returned alongside each answer's evaluation under
`competency_update`, and can be read in full via
`GET /interview/{interview_id}/competency`.


## 14. Implementation Status: Timer and Interview Integrity (Stage 3.6)

**Default time limit:** every question gets a 90-second time budget
(`DEFAULT_QUESTION_TIME_LIMIT_SECONDS` in `app/config.py`) — a single
constant, not hard-coded per file.

**IMPORTANT ARCHITECTURE LIMITATION:** the backend cannot observe a
browser's visible countdown, its clipboard, tab switches, or window
focus. A future frontend is responsible for rendering the countdown
and for reporting copy/paste events; the backend only validates and
timestamps what it's told.

**Server-side timing is authoritative.** `question_started_at` is
recorded once (in UTC) the moment a question becomes current, and is
never reset — not even by resubmitting. Every answer submission
computes `elapsed_seconds` and `timed_out` itself, from its own
`question_started_at` and the current server time, regardless of what
the client claims via `submission_reason`. This is what prevents a
candidate from extending their time by submitting more than once.

**Automatic submission** at 90 seconds is a frontend responsibility:
the backend cannot push a submission from the server, so when a
browser's own countdown reaches zero, it is expected to call the
existing `POST /interview/{id}/answer` endpoint itself with
`submission_reason: "timeout"`. The backend still independently
verifies whether a timeout actually occurred; a late submission is
evaluated and stored as normal, just flagged `timed_out: true` for
audit, since this stage does not implement automatically ending or
advancing past a question.

**Copy/paste integrity events** (`event_type: "copy" | "paste"`) are
client-reported and stored verbatim as metadata alongside each answer
— no clipboard content is ever collected. Their presence is an
indicator for later human review, never an automatic accusation:
submitting a copy/paste event never blocks, penalizes, or otherwise
changes an answer's evaluation or competency update. Advanced
anti-cheating monitoring (tab-switch detection, window-focus tracking,
etc.) is explicitly out of scope for this MVP.


## 15. Implementation Status: Adaptive Math Foundations

`app/services/adaptive_metrics.py` provides pure, deterministic functions
for H(theta), IDI, DifficultyFit and QScore. They are **not** connected to
question selection or any API route, and nothing here is empirically
validated. Apart from theta (Stage 3.5), IDI, DifficultyFit and QScore are
clearly labeled *proposed baselines*. Full definitions, assumptions,
limitations and open questions are in `docs/MATHEMATICAL_SPEC.md`.
Adaptive question selection is still **not** implemented.