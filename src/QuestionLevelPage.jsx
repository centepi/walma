import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { getAuth } from "firebase/auth";
import { db } from "./firebaseConfig";
import { doc, updateDoc, arrayUnion } from "firebase/firestore";
import MathText from "./Mathtext.jsx";
import "katex/dist/katex.css";
import "./LevelPage.css";
import completionGifs from "./loadGifs";

function QuestionLevelPage({ levelData, weekId, levelId, moduleName }) {
  const navigate = useNavigate();
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [selectedAnswer, setSelectedAnswer] = useState(null);
  const [isAnswerChecked, setIsAnswerChecked] = useState(false);
  const [showFeedback, setShowFeedback] = useState(null);
  const [showExplanation, setShowExplanation] = useState(false);
  const [isLevelComplete, setIsLevelComplete] = useState(false);
  const [showSettingsPopup, setShowSettingsPopup] = useState(false);
  const [showQuitPopup, setShowQuitPopup] = useState(false);

  const handleCheckAnswer = () => {
    const currentQuestion = levelData.questions[currentStepIndex];
    const isCorrect = selectedAnswer === currentQuestion.correctAnswer;

    setIsAnswerChecked(true);
    setShowFeedback({
      text: isCorrect
        ? "Correct!"
        : `Incorrect. The answer is: ${currentQuestion.correctAnswer}`,
      isCorrect,
    });

    if (!isCorrect) {
      setShowExplanation(true);
    }
  };

  const handleContinue = () => {
    if (currentStepIndex < levelData.questions.length - 1) {
      setCurrentStepIndex((prev) => prev + 1);
      setIsAnswerChecked(false);
      setSelectedAnswer(null);
      setShowFeedback(null);
      setShowExplanation(false);
    } else {
      setIsLevelComplete(true);
    }
  };

  useEffect(() => {
    const markLevelComplete = async () => {
      if (!isLevelComplete) return;
      const auth = getAuth();
      const user = auth.currentUser;
      if (!user) return;

      try {
        const userRef = doc(db, "Users", user.uid);
        await updateDoc(userRef, {
          completedLevels: arrayUnion(levelId),
        });
        console.log("✅ Question level marked as complete:", levelId);
      } catch (error) {
        console.error("❌ Error saving level completion:", error);
      }
    };

    markLevelComplete();
  }, [isLevelComplete, levelId]);

  const currentQuestion = levelData.questions[currentStepIndex];

  const renderParts = (partsArray) =>
    partsArray.map((part, index) => {
      if (/\.(png|jpg|jpeg)/i.test(part)) {
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
        return (
          <p key={index}>
            <MathText>{part}</MathText>
          </p>
        );
      }
    });

  return (
    <div className="level-container-page">
      <div className="settings-button" onClick={() => setShowSettingsPopup(true)}>☰</div>

      {showSettingsPopup && (
        <>
          <div className="popup-backdrop" />
          <div className="settings-popup">
            <div className="settings-title">Settings</div>
            <div className="settings-buttons">
              <button className="done-button" onClick={() => setShowSettingsPopup(false)}>
                Done
              </button>
              <button
                className="end-session-button"
                onClick={() => {
                  setShowSettingsPopup(false);
                  if (currentStepIndex === 0) {
                    navigate(`/map/${moduleName}`);
                  } else {
                    setShowQuitPopup(true);
                  }
                }}
              >
                End Session
              </button>
            </div>
          </div>
        </>
      )}

      {showQuitPopup && (
        <>
          <div className="popup-backdrop" />
          <div className="quit-popup">
            <div className="quit-message">
              You’ve already made progress. If you quit now, your progress will be lost. Are you sure?
            </div>
            <div className="quit-buttons">
              <button className="keep-learning-button" onClick={() => setShowQuitPopup(false)}>
                Keep Learning
              </button>
              <button className="quit-button" onClick={() => navigate(`/map/${moduleName}`)}>Quit</button>
            </div>
          </div>
        </>
      )}

      <div className="progress-bar">
        <div
          className="progress-fill"
          style={{ width: `${((currentStepIndex + 1) / levelData.questions.length) * 100}%` }}
        />
      </div>

      {isLevelComplete ? (
        <div className="level-complete">
          <h2>LEVEL COMPLETE!</h2>
          <img
            src={completionGifs[Math.floor(Math.random() * completionGifs.length)]}
            alt="Congratulations"
            className="completion-gif"
          />
          <button className="finish-button" onClick={() => navigate(`/map/${moduleName}`)}>
            FINISH
          </button>
        </div>
      ) : (
        <div className="question-explanation-wrapper">
          <div className="question-card">
            <div className="question-content">
              {renderParts(currentQuestion.questionParts)}
            </div>

            <div className="options">
              {currentQuestion.options.map((option, i) => (
                <button
                  key={i}
                  className={`option ${selectedAnswer === option ? "selected" : ""} ${isAnswerChecked ? "disabled" : ""}`}
                  onClick={() => setSelectedAnswer(option)}
                  disabled={isAnswerChecked}
                >
                  <MathText>{option}</MathText>
                </button>
              ))}
            </div>

            {isAnswerChecked && (
              <div className={`feedback ${showFeedback.isCorrect ? "correct" : "incorrect"}`}>
                <p><MathText>{showFeedback.text}</MathText></p>
              </div>
            )}

            <div className="fixed-bottom-buttons">
              {isAnswerChecked && showFeedback.isCorrect && (
                <button className="why-button" onClick={() => setShowExplanation((prev) => !prev)}>
                  WHY?
                </button>
              )}

              <button
                className={`check-button ${selectedAnswer ? "enabled" : ""} ${isAnswerChecked ? "continue-mode" : ""}`}
                onClick={selectedAnswer ? (isAnswerChecked ? handleContinue : handleCheckAnswer) : undefined}
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
