import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { db } from "./firebaseConfig";
import { doc, getDoc } from "firebase/firestore";
import ReviewLevelPage from "./ReviewLevelPage";
import QuestionLevelPage from "./QuestionLevelPage";

function LevelPage() {
  const { weekId, levelId } = useParams();
  const [selectedLevel, setSelectedLevel] = useState(null);

  // 🧠 Extract module name from weekId like "calc2_week1" → "calc2"
  const moduleName = weekId.split("_")[0];

  useEffect(() => {
    const fetchLevelData = async () => {
      try {
        const levelRef = doc(db, `Weeks/${weekId}/Levels/${levelId}`);
        const levelSnap = await getDoc(levelRef);

        if (!levelSnap.exists()) {
          console.error("❌ No such level found: ", levelId);
          return;
        }

        const levelData = levelSnap.data();
        setSelectedLevel(levelData);
      } catch (error) {
        console.error("❌ Error fetching level data:", error);
      }
    };

    fetchLevelData();
  }, [weekId, levelId]);

  if (!selectedLevel) return <div className="loading">Loading level...</div>;

  return selectedLevel.type === "review" ? (
    <ReviewLevelPage
      levelData={selectedLevel}
      weekId={weekId}
      levelId={levelId}
      moduleName={moduleName} // ✅ Pass this to child component
    />
  ) : (
    <QuestionLevelPage
      levelData={selectedLevel}
      weekId={weekId}
      levelId={levelId}
      moduleName={moduleName} // ✅ Pass this to child component
    />
  );
}

export default LevelPage;
