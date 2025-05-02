import React, { useState } from "react";
import { auth } from "./firebaseConfig";
import { signInWithEmailAndPassword, signInWithPopup, GoogleAuthProvider } from "firebase/auth";
import { useNavigate } from "react-router-dom";
import "./LoginPage.css";

function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  const handleLogin = async (e) => {
    e.preventDefault();
    try {
      const userCredential = await signInWithEmailAndPassword(auth, email, password);
      const user = userCredential.user;

      // ✅ Store user's name and email in local storage (for immediate UI update)
      localStorage.setItem("user", JSON.stringify({ displayName: user.displayName, email: user.email }));

      navigate("/"); // ✅ Redirect to Home Page after login
    } catch (error) {
      if (error.code === "auth/user-not-found") {
        setError("No account found with this email. Try signing up.");
      } else if (error.code === "auth/wrong-password") {
        setError("Incorrect password. Please try again.");
      } else if (error.code === "auth/invalid-email") {
        setError("Please enter a valid email address.");
      } else {
        setError("Login failed. Please check your details and try again.");
      }
    }
  };

  const handleGoogleLogin = async () => {
    const provider = new GoogleAuthProvider();
    try {
      const userCredential = await signInWithPopup(auth, provider);
      const user = userCredential.user;

      // ✅ Store Google user's name and email in local storage (for immediate UI update)
      localStorage.setItem("user", JSON.stringify({ displayName: user.displayName, email: user.email }));

      navigate("/"); // ✅ Redirect to Home Page after Google login
    } catch (error) {
      setError("Google login failed. Please try again.");
    }
  };

  return (
    <div className="login-container">
      {/* Home Button */}
      <button className="auth-home-button" onClick={() => navigate("/")}>Home</button>
      
      {/* WALMA Title */}
      <h1 className="login-title">WALMA</h1>
      <p className="login-info">Welcome back! Log in to continue your progress.</p>

      {/* Error Message */}
      {error && <p className="error-message">{error}</p>}
      
      {/* Login Box - Now Matches Sign-Up Page */}
      <div className="login-box">
        <form onSubmit={handleLogin} className="login-form">
          <input 
            type="email" 
            placeholder="Email" 
            className="login-input" 
            value={email} 
            onChange={(e) => setEmail(e.target.value)} 
            required 
          />
          <input 
            type="password" 
            placeholder="Password" 
            className="login-input" 
            value={password} 
            onChange={(e) => setPassword(e.target.value)} 
            required 
          />
          <button type="submit" className="login-button">Log In</button>
        </form>
      </div>

      {/* "or" Separator */}
      <p className="or-text">or</p>

      {/* Google Login Button */}
      <button onClick={handleGoogleLogin} className="google-login-button">
        Log In with Google
      </button>

      {/* Redirect to Sign-Up Page */}
      <p className="signup-text">Don’t have an account? <a href="/signup">Sign Up</a></p>
    </div>
  );
}

export default LoginPage;