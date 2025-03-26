import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { getAuth } from "firebase/auth";
import { db } from "./firebaseConfig";
import { doc, getDoc, setDoc } from "firebase/firestore";
import { InlineMath, BlockMath } from "react-katex";
import "katex/dist/katex.css";
import "./LevelPage.css";
import completionGifs from "./loadGifs";

function QuestionLevelPage({ levelData, weekId, levelId }) {
  const navigate = useNavigate();
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [selectedAnswer, setSelectedAnswer] = useState(null);
  const [isAnswerChecked, setIsAnswerChecked] = useState(false);
  const [showFeedback, setShowFeedback] = useState(null);
  const [showExplanation, setShowExplanation] = useState(false);
  const [isLevelComplete, setIsLevelComplete] = useState(false);

  const handleCheckAnswer = () => {
    const currentQuestion = levelData.questions[currentStepIndex];
    const isCorrect = selectedAnswer === currentQuestion.correctAnswer;

    setIsAnswerChecked(true);
    setShowFeedback({
      text: isCorrect
        ? "Correct!"
        : `Incorrect. The answer is: ${currentQuestion.correctAnswer}`,
      isCorrect: isCorrect,
    });

    if (!isCorrect) {
      setShowExplanation(true);
    }
  };

  const handleContinue = async () => {
    if (currentStepIndex < levelData.questions.length - 1) {
      setCurrentStepIndex((prev) => prev + 1);
      setIsAnswerChecked(false);
      setSelectedAnswer(null);
      setShowFeedback(null);
      setShowExplanation(false);
    } else {
      await markLevelComplete();
      setIsLevelComplete(true);
    }
  };

  const markLevelComplete = async () => {
    try {
      const auth = getAuth();
      const user = auth.currentUser;
      if (!user) return;

      const userRef = doc(db, "Users", user.uid);
      const userSnap = await getDoc(userRef);

      if (userSnap.exists()) {
        const userData = userSnap.data();
        const updatedCompletedLevels = [...(userData.completedLevels || []), levelId];

        await setDoc(userRef, { completedLevels: updatedCompletedLevels }, { merge: true });
      }
    } catch (error) {
      console.error("❌ Error marking level complete:", error);
    }
  };

  const currentQuestion = levelData.questions[currentStepIndex];

  const renderInlineMathText = (text) => {
    return text.split("\n").map((line, lineIndex) => (
      <React.Fragment key={lineIndex}>
        {line.split(/\{\{(.*?)\}\}/g).map((seg, i) =>
          i % 2 === 1 ? <InlineMath key={i} math={seg.trim()} /> : seg
        )}
        <br />
      </React.Fragment>
    ));
  };

  const renderParts = (partsArray) =>
    partsArray.map((part, index) => {
      if (part.trim() === part.trim().replace(/[a-zA-Z0-9 .,!?]/g, "").length > 2) {
        // If mostly symbols and math, show block
        return <BlockMath key={index} math={part.trim()} />;
      } else if (part.toLowerCase().includes(".png") || part.toLowerCase().includes(".jpg")) {
        return (
          <img
            key={index}
            src={`/${part.trim()}`}
            alt="Diagram"
            className="diagram"
            onError={() => console.error(`Image not found: /${part.trim()}`)}
          />
        );
      } else {
        return <p key={index}>{renderInlineMathText(part)}</p>;
      }
    });

  return (
    <div className="level-container-page">
      <div className="progress-bar">
        <div
          className="progress-fill"
          style={{ width: `${((currentStepIndex + 1) / levelData.questions.length) * 100}%` }}
        ></div>
      </div>

      {isLevelComplete ? (
        <div className="level-complete">
          <h2>LEVEL COMPLETE!</h2>
          <img
            src={completionGifs[Math.floor(Math.random() * completionGifs.length)]}
            alt="Congratulations"
            className="completion-gif"
          />
          <button className="finish-button" onClick={() => navigate("/map")}>FINISH</button>
        </div>
      ) : (
        <div className="question-explanation-wrapper">
          <div className="question-card">
            <div className="question-content">{renderParts(currentQuestion.questionParts)}</div>

            <div className="options">
              {currentQuestion.options.map((option, i) => (
                <button
                  key={i}
                  className={`option ${selectedAnswer === option ? "selected" : ""} ${isAnswerChecked ? "disabled" : ""}`}
                  onClick={() => setSelectedAnswer(option)}
                  disabled={isAnswerChecked}
                >
                  {renderInlineMathText(option)}
                </button>
              ))}
            </div>

            {isAnswerChecked && (
              <div className={`feedback ${showFeedback.isCorrect ? "correct" : "incorrect"}`}>
                <p>{renderInlineMathText(showFeedback.text)}</p>
              </div>
            )}

            <div className="fixed-bottom-buttons">
              {isAnswerChecked && showFeedback.isCorrect && (
                <button
                  className="why-button"
                  onClick={() => setShowExplanation((prev) => !prev)}
                >
                  WHY?
                </button>
              )}

              <button
                className={`check-button ${selectedAnswer ? "enabled" : ""} ${isAnswerChecked ? "continue-mode" : ""}`}
                onClick={isAnswerChecked ? handleContinue : handleCheckAnswer}
                disabled={!selectedAnswer}
              >
                {isAnswerChecked ? (showFeedback.isCorrect ? "Continue" : "Got It") : "Check"}
              </button>
            </div>
          </div>

          <div className={`explanation-card ${showExplanation ? "show" : ""}`}>
            <h3>Explanation:</h3>
            {renderParts(currentQuestion.explanationParts)}
          </div>
        </div>
      )}
    </div>
  );
}

export default QuestionLevelPage;
