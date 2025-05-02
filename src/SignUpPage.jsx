import React, { useState } from "react";
import { auth } from "./firebaseConfig";
import { createUserWithEmailAndPassword, updateProfile, signInWithPopup, GoogleAuthProvider } from "firebase/auth";
import { useNavigate } from "react-router-dom";
import "./SignUpPage.css";

function SignUpPage() {
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  const handleSignUp = async (e) => {
    e.preventDefault();
    try {
      const userCredential = await createUserWithEmailAndPassword(auth, email, password);
      const user = userCredential.user;

      // ✅ Update Firebase user profile with first & last name
      await updateProfile(user, {
        displayName: `${firstName} ${lastName}`
      });

      // ✅ Store user info in local storage (so name updates immediately)
      localStorage.setItem("user", JSON.stringify({ displayName: `${firstName} ${lastName}`, email }));

      navigate("/"); // ✅ Redirect to Home Page after sign-up
    } catch (error) {
      if (error.code === "auth/email-already-in-use") {
        setError("An account with this email already exists. Try logging in instead.");
      } else if (error.code === "auth/invalid-email") {
        setError("Please enter a valid email address.");
      } else if (error.code === "auth/weak-password") {
        setError("Your password is too weak. Try using at least 6 characters.");
      } else {
        setError("Sign-up failed. Please try again.");
      }
    }
  };

  const handleGoogleSignUp = async () => {
    const provider = new GoogleAuthProvider();
    try {
      const userCredential = await signInWithPopup(auth, provider);
      const user = userCredential.user;

      // ✅ Store Google user's name & email in local storage
      localStorage.setItem("user", JSON.stringify({ displayName: user.displayName, email: user.email }));

      navigate("/"); // ✅ Redirect to Home Page after Google sign-up
    } catch (error) {
      setError("Google sign-up failed. Please try again.");
    }
  };

  return (
    <div className="signup-container">
      {/* Home Button */}
      <button className="auth-home-button" onClick={() => navigate("/")}>Home</button>

      <h1 className="signup-title">WALMA</h1>
      <p className="signup-subtext">Create an account to save your progress.</p>

      {error && <p className="error-message">{error}</p>}

      <div className="signup-box">
        <form onSubmit={handleSignUp} className="signup-form">
          <input 
            type="text" 
            placeholder="First Name" 
            value={firstName} 
            onChange={(e) => setFirstName(e.target.value)} 
            required 
          />
          <input 
            type="text" 
            placeholder="Last Name" 
            value={lastName} 
            onChange={(e) => setLastName(e.target.value)} 
            required 
          />
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <button type="submit" className="signup-btn">Sign Up</button>
        </form>
      </div>

      <p className="or-text">or</p>

      <button onClick={handleGoogleSignUp} className="google-signup-button">
        Sign Up with Google
      </button>

      <p className="login-text">Already have an account? <a href="/login">Log In</a></p>
    </div>
  );
}

export default SignUpPage;
