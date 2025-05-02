import { initializeApp, getApps, getApp } from "firebase/app";
import { getFirestore, doc, setDoc } from "firebase/firestore";
import firebaseConfig from "./firebaseConfig.js"; // ✅ Ensure correct Firebase config

// ✅ Prevent Duplicate Firebase Initialization
const app = getApps().length === 0 ? initializeApp(firebaseConfig) : getApp();
const db = getFirestore(app);

(async () => {
  try {
    await setDoc(doc(db, "TestCollection", "TestDoc"), { message: "Hello from WALMA!" });
    console.log("✅ Firestore Write Successful!");
  } catch (error) {
    console.error("❌ Firestore Write Failed:", error);
  }
})();
