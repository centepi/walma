import "./App.css";
import { Routes, Route, useNavigate, Navigate } from "react-router-dom";
import { useState, useEffect } from "react";
import { auth } from "./firebaseConfig.js";
import { signOut, onAuthStateChanged } from "firebase/auth";
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
    // ✅ Check Local Storage First
    const storedUser = localStorage.getItem("user");
    if (storedUser) {
      setUser(JSON.parse(storedUser));
      setIsAuthChecked(true);
    }

    // ✅ Firebase Auth Listener
    const unsubscribe = onAuthStateChanged(auth, (currentUser) => {
      setUser(currentUser);
      setIsAuthChecked(true);

      if (currentUser) {
        localStorage.setItem("user", JSON.stringify(currentUser));
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
      {/* Three-bars menu icon */}
      <button onClick={toggleHomeSettings} className="home-menu-button">☰</button>

      {/* Home Settings Sidebar */}
      <div className={`home-settings-sidebar ${isHomeSettingsOpen ? "open" : ""}`}>
        <h2 className="home-settings-title">
          Hi, {user && user.displayName ? user.displayName : "Guest"}
        </h2>

        {/* Sign In / Sign Out Button */}
        <button onClick={user ? handleSignOut : goToSignUp} className="home-settings-button">
          {user ? "Sign Out" : "Sign In"}
        </button>

        {/* Log In Button */}
        {!user && (
          <button onClick={() => navigate("/login")} className="home-settings-button">
            Log In
          </button>
        )}

        {/* Account Settings Button */}
        <button className="home-settings-button" onClick={() => navigate("/account-settings")}>
          Account Settings
        </button>
      </div>

      <div className="title-container">
        <h1 className="title">
          <span>W</span>
          <span>A</span>
          <span>L</span>
          <span>M</span>
          <span>A</span>
        </h1>

        {/* Whale Animation */}
        <img src={whaleAnimation} alt="Whale" className="whale" />
      </div>

      {/* Course Buttons */}
      <div className="button-container">
        <FloatingButton isComingSoon={true}>Dynamical Systems</FloatingButton>

        <FloatingButton
          onClick={() => {
            if (!isAuthChecked) return;
            if (user) {
              console.log("✅ User found. Navigating to /map...");
              navigate("/map");
            } else {
              console.log("❌ No user found. Navigating to /signup...");
              navigate("/signup");
            }
          }}
        >
          Calculus II
        </FloatingButton>
      </div>

      {/* Bubbles in Background */}
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

  if (!isAuthChecked) return null; // ✅ Prevents redirecting before auth check completes

  return user ? children : <Navigate to="/signup" />;
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/signup" element={<SignUpPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/map" element={<ProtectedRoute><MapPage /></ProtectedRoute>} />
      <Route path="/level/:weekId/:levelId" element={<ProtectedRoute><LevelPage /></ProtectedRoute>} />
      <Route path="/account-settings" element={<AccountSettingsPage />} />
    </Routes>
  );
}

export default App;