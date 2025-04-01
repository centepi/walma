import React, { useEffect, useState, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getAuth, onAuthStateChanged } from "firebase/auth";
import { db } from "./firebaseConfig";
import { collection, getDocs, doc, getDoc } from "firebase/firestore";
import "./MapPage.css";

import buttonA from "./assets/button_A.png";

function MapPage() {
  const [weeks, setWeeks] = useState([]);
  const [completedLevels, setCompletedLevels] = useState([]);
  const [selectedLevel, setSelectedLevel] = useState(null);
  const [popupPosition, setPopupPosition] = useState({ top: 0, left: 0 });
  const { moduleName } = useParams();
  const navigate = useNavigate();
  const levelRefs = useRef({});
  const auth = getAuth();

  // 🔁 Redirect if moduleName is missing or invalid
  useEffect(() => {
    if (!moduleName || moduleName === "undefined") {
      console.warn("Invalid module name — redirecting to default module.");
      navigate("/map/ds", { replace: true });
    }
  }, [moduleName, navigate]);

  // 🔐 Load completedLevels from Firestore
  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      if (user) {
        const userRef = doc(db, "Users", user.uid);
        try {
          const userSnap = await getDoc(userRef);
          if (userSnap.exists()) {
            setCompletedLevels(userSnap.data().completedLevels || []);
          }
        } catch (error) {
          console.error("Error fetching completed levels:", error);
        }
      }
    });

    return () => unsubscribe();
  }, []);

  // 🧠 Fetch weeks & levels for this module
  useEffect(() => {
    const fetchWeeksAndLevels = async () => {
      const weeksCollection = collection(db, "Weeks");
      const weeksSnapshot = await getDocs(weeksCollection);
      if (weeksSnapshot.empty) return;

      const fetchedWeeks = [];
      for (const weekDoc of weeksSnapshot.docs) {
        const weekDocData = weekDoc.data();
        if (weekDocData.module !== moduleName) continue;

        const weekData = { id: weekDoc.id, ...weekDocData, levels: [] };

        const levelsCollection = collection(db, `Weeks/${weekDoc.id}/Levels`);
        const levelsSnapshot = await getDocs(levelsCollection);

        let sortedLevels = levelsSnapshot.docs.map((doc) => {
          const firestoreLevel = { id: doc.id, weekId: weekDoc.id, ...doc.data() };
          const weekLevelMeta = weekDocData.levels.find((l) => l.id === doc.id);
          return {
            ...firestoreLevel,
            title: firestoreLevel.title || weekLevelMeta?.title || "Level",
          };
        });

        // Sort: review first, then by level number
        sortedLevels.sort((a, b) => {
          if (a.type === "review") return -1;
          if (b.type === "review") return 1;
          return (a.levelNumber || 0) - (b.levelNumber || 0);
        });

        // No locking – all levels are shown
        sortedLevels = sortedLevels.map((level) => ({
          ...level,
          isUnlocked: true,
        }));

        weekData.levels = sortedLevels;
        fetchedWeeks.push(weekData);
      }

      // Log fetched weeks data
      console.log("Fetched weeks data:", fetchedWeeks);
      setWeeks(fetchedWeeks);
    };

    fetchWeeksAndLevels();
  }, [completedLevels, moduleName]);

  // 📍 Level click logic
  const handleLevelClick = (levelId) => {
    if (selectedLevel?.id === levelId) {
      setSelectedLevel(null);
      return;
    }

    const levelElement = levelRefs.current[levelId];
    if (levelElement) {
      const rect = levelElement.getBoundingClientRect();
      setPopupPosition({
        top: rect.top + window.scrollY - 10,
        left: rect.left + rect.width + 15,
      });
    }

    let selected = null;
    for (const week of weeks) {
      const level = week.levels.find((lvl) => lvl.id === levelId);
      if (level) {
        selected = level;
        break;
      }
    }

    setSelectedLevel(selected);
  };

  // Log the moduleName and weeks data before rendering
  console.log("Module Name:", moduleName);
  console.log("Weeks Data:", weeks);

  return (
    <div className="map-container">
      <div className="bubbles">
        {Array.from({ length: 15 }).map((_, i) => (
          <span key={i} className="bubble"></span>
        ))}
      </div>

      <div className="top-right-controls">
        <button onClick={() => navigate("/")} className="nav-button">Home</button>
        <button onClick={() => navigate("/account-settings")} className="nav-button">
          Account Settings
        </button>
      </div>

      <div className="weeks-wrapper">
        {weeks.map((week) => (
          <div key={week.id} className="week-container">
            <div className="week-tab">
              <h2>{week.title}</h2>
              <p>{week.description}</p>
            </div>
            <div className="levels-wrapper">
              {week.levels.map((level) => (
                <div key={level.id} className="level-container">
                  <img
                    ref={(el) => (levelRefs.current[level.id] = el)}
                    src={buttonA}
                    className={`level-button ${
                      completedLevels.includes(level.id) ? "completed" : ""
                    }`}
                    onClick={() => handleLevelClick(level.id)}
                    alt="Level Button"
                  />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {selectedLevel && (
        <div
          className="level-info-box"
          style={{ top: popupPosition.top, left: popupPosition.left }}
        >
          <h3>{selectedLevel.title}</h3>
          <button
            className="start-button"
            onClick={() =>
              navigate(`/level/${selectedLevel.weekId}/${selectedLevel.id}`)
            }
          >
            Start
          </button>
        </div>
      )}
    </div>
  );
}

export default MapPage;
