import { db } from "./firebaseConfig.js";
import { collection, getDocs } from "firebase/firestore";

const debugLevels = async () => {
  const levelsCollection = collection(db, "Levels");
  const levelsSnapshot = await getDocs(levelsCollection);

  console.log("🔥 Debugging Level Data in Firebase:");
  levelsSnapshot.docs.forEach((doc) => {
    console.log(doc.id, "➡️", doc.data());
  });
};

debugLevels();
