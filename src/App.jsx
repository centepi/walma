import "./App.css";
import { Routes, Route, useNavigate, Navigate } from "react-router-dom";
import { useState, useEffect } from "react";
import { auth, db } from "./firebaseConfig";
import { signOut, onAuthStateChanged } from "firebase/auth";
import { doc, getDoc, setDoc } from "firebase/firestore";

import FloatingButton from "./FloatingButton";
import MapPage from "./MapPage";
import LevelPage from "./LevelPage";
import SignUpPage from "./SignUpPage";
import LoginPage from "./LoginPage";
import AccountSettingsPage from "./AccountSettingsPage";
import whaleAnimation from "./assets/whale.png";

function HomePage() {
  const [user, setUser] = useState(null);
  const [isAuthChecked, setIsAuthChecked] = useState(false);
  const [isHomeSettingsOpen, setIsHomeSettingsOpen] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const storedUser = localStorage.getItem("user");
    if (storedUser) {
      setUser(JSON.parse(storedUser));
      setIsAuthChecked(true);
    }

    const unsubscribe = onAuthStateChanged(auth, async (currentUser) => {
      setUser(currentUser);
      setIsAuthChecked(true);

      if (currentUser) {
        localStorage.setItem("user", JSON.stringify(currentUser));

        const userRef = doc(db, "Users", currentUser.uid);
        const userSnap = await getDoc(userRef);

        if (!userSnap.exists()) {
          console.warn("👻 No user doc yet — creating it...");
          await setDoc(userRef, { completedLevels: [] });
        }
      } else {
        localStorage.removeItem("user");
      }
    });

    return () => unsubscribe();
  }, []);

  const goToSignUp = () => navigate("/signup");
  const handleSignOut = async () => {
    await signOut(auth);
    setUser(null);
  };
  const toggleHomeSettings = () => setIsHomeSettingsOpen(!isHomeSettingsOpen);

  return (
    <div className="container">
      {/* ☰ Menu */}
      <button onClick={toggleHomeSettings} className="home-menu-button">☰</button>

      {/* Settings Sidebar */}
      <div className={`home-settings-sidebar ${isHomeSettingsOpen ? "open" : ""}`}>
        <h2 className="home-settings-title">
          Hi, {user && user.displayName ? user.displayName : "Guest"}
        </h2>

        <button onClick={user ? handleSignOut : goToSignUp} className="home-settings-button">
          {user ? "Sign Out" : "Sign In"}
        </button>

        {!user && (
          <button onClick={() => navigate("/login")} className="home-settings-button">
            Log In
          </button>
        )}

        <button className="home-settings-button" onClick={() => navigate("/account-settings")}>
          Account Settings
        </button>
      </div>

      {/* Whale + WALMA Title */}
      <div className="hero-container">
        <img src={whaleAnimation} alt="Whale" className="whale" />
        <h1 className="title">
          <span>W</span><span>A</span><span>L</span><span>M</span><span>A</span>
        </h1>
      </div>

      {/* Buttons */}
      <div className="button-container">
        <FloatingButton
          onClick={() => {
            if (!isAuthChecked) return;
            if (user) {
              navigate("/map/ds");
            } else {
              navigate("/signup");
            }
          }}
        >
          Intro to Dynamical Systems
        </FloatingButton>

        <FloatingButton
          onClick={() => {
            if (!isAuthChecked) return;
            if (user) {
              navigate("/map/calc2");
            } else {
              navigate("/signup");
            }
          }}
        >
          Calculus II
        </FloatingButton>
      </div>

      {/* Bubbles */}
      <div className="bubbles">
        <span></span><span></span><span></span><span></span><span></span><span></span><span></span>
      </div>
    </div>
  );
}

function ProtectedRoute({ children }) {
  const [user, setUser] = useState(null);
  const [isAuthChecked, setIsAuthChecked] = useState(false);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (currentUser) => {
      setUser(currentUser);
      setIsAuthChecked(true);
    });

    return () => unsubscribe();
  }, []);

  if (!isAuthChecked) return null;
  return user ? children : <Navigate to="/signup" />;
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/signup" element={<SignUpPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/account-settings" element={<AccountSettingsPage />} />

      {/* ✅ Handles /map/calc2, /map/ds, etc. */}
      <Route path="/map/:moduleName" element={<ProtectedRoute><MapPage /></ProtectedRoute>} />

      {/* ✅ Handles just /map */}
      <Route path="/map" element={<Navigate to="/map/ds" />} />

      {/* ✅ Level pages */}
      <Route path="/level/:weekId/:levelId" element={<ProtectedRoute><LevelPage /></ProtectedRoute>} />
    </Routes>
  );
}

export default App;
