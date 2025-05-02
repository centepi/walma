import React, { useState, useEffect } from "react";
import { auth } from "./firebaseConfig";
import { updateProfile, signOut } from "firebase/auth";
import { useNavigate } from "react-router-dom";
import "./AccountSettingsPage.css";

function AccountSettingsPage() {
  const [user, setUser] = useState(null);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    // ✅ Get user details from Firebase
    const currentUser = auth.currentUser;
    if (currentUser) {
      setUser(currentUser);
      if (currentUser.displayName) {
        const nameParts = currentUser.displayName.split(" ");
        setFirstName(nameParts[0] || "");
        setLastName(nameParts[1] || "");
      }
    }
  }, []);

  const handleSaveChanges = async () => {
    try {
      if (user) {
        await updateProfile(user, {
          displayName: `${firstName} ${lastName}`,
        });

        // ✅ Update Local Storage for instant UI change
        localStorage.setItem("user", JSON.stringify({ displayName: `${firstName} ${lastName}`, email: user.email }));

        setIsEditing(false);
      }
    } catch (error) {
      setError("Failed to update name. Please try again.");
    }
  };

  const handleSignOut = async () => {
    await signOut(auth);
    localStorage.removeItem("user");
    navigate("/"); // ✅ Redirect to home after sign-out
  };

  return (
    <div className="account-settings-container">
      {/* Home Button */}
      <button className="auth-home-button" onClick={() => navigate("/")}>Home</button>

      <h1 className="account-settings-title">Account Settings</h1>

      {error && <p className="error-message">{error}</p>}

      <div className="account-settings-box">
        {/* User Name */}
        {isEditing ? (
          <>
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
            <button className="save-button" onClick={handleSaveChanges}>Save Changes</button>
          </>
        ) : (
          <>
            <p><strong>Name:</strong> {firstName} {lastName}</p>
            <button className="edit-button" onClick={() => setIsEditing(true)}>Edit</button>
          </>
        )}

        {/* Email */}
        <p><strong>Email:</strong> {user?.email}</p>

        {/* Login Method */}
        <p><strong>Login Method:</strong> {user?.providerData[0]?.providerId === "password" ? "Email & Password" : "Google"}</p>

        {/* Sign Out Button */}
        <button className="signout-button" onClick={handleSignOut}>Sign Out</button>
      </div>

    {/* Feedback Section */}
    <div className="feedback-box">
    <p className="feedback-text">
        If you have any problems or thoughts about the website, I’d appreciate your feedback!  
        You can email me at <strong>benjamin.jobbagy@icloud.com</strong>.
    </p>
    </div>
    </div>
  );
}

export default AccountSettingsPage;