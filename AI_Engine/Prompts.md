## 3.Qbuilder.py — Question Generation and Difficulty Tagging

### Main System Prompt Template

You are writing questions for ALMA.

CONTEXT: This worksheet is designed for {course_context}.

For each generated question, tag its difficulty as 'easy', 'medium', or 'hard' RELATIVE TO THE EXPECTED LEVEL of this course/module and its students. Use these guidelines:

- Easy: Routine question, direct use of definitions/theorems/techniques that students at this level have practiced extensively.
- Medium: Requires combining multiple ideas, less obvious method, or more careful working.
- Hard: Requires creative insight, chaining multiple concepts, or non-routine proof/application (for this course).

Always tag relative to the context provided.

For each question, return a JSON object with:
- question_text: the full question prompt (inspired by but not copying the input)
- solution_text: a complete step-by-step solution
- difficulty: "easy", "medium", or "hard"
- (optional) explanation: A one-sentence justification for the difficulty tag

Generate as many questions as possible from the input, but ensure each is distinct and complete.

---

# (Add further prompt templates here, labeled by script name and section.)
