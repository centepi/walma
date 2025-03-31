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
      <div className="progress-bar">
        <div
          className="progress-fill"
          style={{ width: `${((currentStepIndex + 1) / levelData.slides.length) * 100}%` }}
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
