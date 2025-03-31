import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { InlineMath, BlockMath } from "react-katex";
import { doc, updateDoc, arrayUnion } from "firebase/firestore";
import { auth, db } from "./firebaseConfig";
import "katex/dist/katex.css";
import "./LevelPage.css";
import completionGifs from "./loadGifs";

function ReviewLevelPage({ levelData, weekId, levelId, moduleName }) {
  const navigate = useNavigate();
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [isLevelComplete, setIsLevelComplete] = useState(false);
  const [showSettingsPopup, setShowSettingsPopup] = useState(false);
  const [showQuitPopup, setShowQuitPopup] = useState(false);

  const handleContinue = () => {
    if (currentStepIndex < levelData.slides.length - 1) {
      setCurrentStepIndex((prev) => prev + 1);
    } else {
      setIsLevelComplete(true);
    }
  };

  // Save to Firestore when level is marked complete
  useEffect(() => {
    const markComplete = async () => {
      if (!isLevelComplete) return;
      const user = auth.currentUser;
      if (!user) return;

      try {
        const userRef = doc(db, "Users", user.uid);
        await updateDoc(userRef, {
          completedLevels: arrayUnion(levelId),
        });
        console.log("✅ Review level saved:", levelId);
      } catch (error) {
        console.error("❌ Failed to save review level:", error);
      }
    };

    markComplete();
  }, [isLevelComplete, levelId]);

  const currentSlide = levelData.slides[currentStepIndex];

  const resolveDiagramPath = (path) => {
    if (!path) return null;
    return path.startsWith("http") ? path : `/diagrams/${path}`;
  };

  return (
    <div className="level-container-page">
      {/* ☰ Settings Button */}
      <div className="settings-button" onClick={() => setShowSettingsPopup(true)}>☰</div>

      {/* Settings Popup */}
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
                    navigate("/map");
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

      {/* Quit Confirmation Popup */}
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
              <button className="quit-button" onClick={() => navigate("/map")}>Quit</button>
            </div>
          </div>
        </>
      )}

      {/* Progress Bar */}
      <div className="progress-bar">
        <div
          className="progress-fill"
          style={{ width: `${((currentStepIndex + 1) / levelData.slides.length) * 100}%` }}
        />
      </div>

      {/* Content */}
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
        <div className="review-box">
          <h2>{currentSlide.title}</h2>
          <p>
            {currentSlide.contentBeforeEquation && currentSlide.contentBeforeEquation + " "}
            {currentSlide.inlineEquation && <InlineMath math={currentSlide.inlineEquation} />}
            {currentSlide.contentAfterEquation && " " + currentSlide.contentAfterEquation + " "}
            {currentSlide.inlineEquation2 && <InlineMath math={currentSlide.inlineEquation2} />}
            {currentSlide.contentEnd && " " + currentSlide.contentEnd}
            {currentSlide.content && currentSlide.content}
          </p>

          {currentSlide.equation && <BlockMath math={currentSlide.equation} />}

          {currentSlide.diagram && (
            <img
              src={resolveDiagramPath(currentSlide.diagram)}
              alt="Diagram"
              className="diagram"
              onError={() =>
                console.error(`Image not found: ${resolveDiagramPath(currentSlide.diagram)}`)
              }
            />
          )}

          <button className="continue-button" onClick={handleContinue}>
            Continue
          </button>
        </div>
      )}
    </div>
  );
}

export default ReviewLevelPage;
