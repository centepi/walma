import { initializeApp } from "firebase/app";
import { getAuth, onAuthStateChanged } from "firebase/auth";
import { getFirestore, doc, getDoc, setDoc } from "firebase/firestore";
import { getStorage } from "firebase/storage"; // ✅ Import Firebase Storage

// 🔹 Firebase Configuration
const firebaseConfig = {
  apiKey: "AIzaSyAqeI03Y4Q7JVv02Cov153vl8q7y_s-ev8",
  authDomain: "walma-609e7.firebaseapp.com",
  projectId: "walma-609e7",
  storageBucket: "walma-609e7.appspot.com", // ✅ Corrected storageBucket
  messagingSenderId: "775732462124",
  appId: "1:775732462124:web:be8b1aa88324c3e7d44789"
};

// 🔹 Initialize Firebase
const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
export const db = getFirestore(app);
export const storage = getStorage(app); // ✅ Initialize and export Firebase Storage

// ✅ Automatically Add User to Firestore on Login
onAuthStateChanged(auth, async (user) => {
  if (user) {
    const userRef = doc(db, "Users", user.uid);
    const userSnap = await getDoc(userRef);

    if (!userSnap.exists()) {
      // 🔹 Create user document if it doesn't exist
      await setDoc(userRef, { completedLevels: [] });
      console.log(`✅ Created user document for: ${user.uid}`);
    }
  }
});

export default app;
