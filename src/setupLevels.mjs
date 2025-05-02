import admin from "firebase-admin";
import { getFirestore } from "firebase-admin/firestore";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const serviceAccountPath = path.join(__dirname, "serviceAccountKey.json");

let serviceAccount;
try {
  serviceAccount = JSON.parse(fs.readFileSync(serviceAccountPath, "utf-8"));
} catch (error) {
  console.error("❌ Error loading serviceAccountKey.json:", error);
  process.exit(1);
}

if (!admin.apps.length) {
  admin.initializeApp({
    credential: admin.credential.cert(serviceAccount),
    storageBucket: "walma-609e7.firebasestorage.app",
  });
}

const db = getFirestore();
const bucket = admin.storage().bucket();

// ✅ Properly loads "week_1.json", "week_2.json", etc.
const loadWeekData = (moduleName, weekFolder) => {
  const weekNumber = weekFolder.replace("week", ""); // "week1" → "1"
  const expectedJsonFile = `week_${weekNumber}.json`; // → "week_1.json"
  const weekDataPath = path.join(__dirname, `modules/${moduleName}/${weekFolder}/${expectedJsonFile}`);
  try {
    return JSON.parse(fs.readFileSync(weekDataPath, "utf-8"));
  } catch (error) {
    console.error(`❌ Error loading ${weekFolder}/${expectedJsonFile}:`, error);
    return null;
  }
};

const deleteExistingWeekData = async (weekId) => {
  try {
    const weekRef = db.collection("Weeks").doc(weekId);
    await weekRef.delete();
  } catch (error) {
    console.error(`❌ Error deleting week ${weekId}:`, error);
  }
};

const uploadDiagramIfNeeded = async (diagramFile, weekId, levelId) => {
  if (diagramFile && !diagramFile.startsWith("http")) {
    const localPath = path.join(__dirname, "..", "public", "diagrams", path.basename(diagramFile));
    if (!fs.existsSync(localPath)) {
      console.error(`❌ Diagram not found: ${localPath}`);
      return diagramFile;
    }

    const storagePath = `diagrams/${weekId}/${levelId}/${path.basename(diagramFile)}`;
    const fileRef = bucket.file(storagePath);

    try {
      await fileRef.save(fs.readFileSync(localPath), {
        gzip: true,
        metadata: { contentType: "image/png" },
      });
      await fileRef.makePublic();

      return `https://storage.googleapis.com/${bucket.name}/${storagePath}`;
    } catch (error) {
      console.error(`❌ Failed to upload diagram ${diagramFile}:`, error);
      return diagramFile;
    }
  }
  return diagramFile;
};

const uploadWeekAndLevels = async (moduleName, weekFolder, weekData) => {
  try {
    const weekRef = db.collection("Weeks").doc(weekData.weekId);

    const enrichedLevels = await Promise.all(weekData.levels.map(async (level) => {
      const levelPath = path.join(__dirname, `modules/${moduleName}/${weekFolder}/${level.id}.json`);
      let levelData;
      try {
        levelData = JSON.parse(fs.readFileSync(levelPath, "utf-8"));
      } catch (error) {
        console.error(`❌ Could not load ${level.id}.json:`, error);
        levelData = {};
      }
      return {
        id: level.id,
        type: level.type,
        title: levelData.title || level.title || "Level",
      };
    }));

    await weekRef.set({
      module: moduleName,
      title: weekData.title || "Untitled Week",
      description: weekData.description || "",
      levels: enrichedLevels,
    });

    for (const level of weekData.levels) {
      const levelPath = path.join(__dirname, `modules/${moduleName}/${weekFolder}/${level.id}.json`);
      let levelData;
      try {
        levelData = JSON.parse(fs.readFileSync(levelPath, "utf-8"));
      } catch (error) {
        console.error(`❌ Could not load ${level.id}.json:`, error);
        continue;
      }

      // ✅ Upload diagrams in slides[]
      if (levelData.slides && Array.isArray(levelData.slides)) {
        for (let i = 0; i < levelData.slides.length; i++) {
          const slide = levelData.slides[i];
          if (slide.diagram) {
            slide.diagram = await uploadDiagramIfNeeded(slide.diagram, weekData.weekId, level.id);
          }
        }
      }

      // ✅ Upload diagrams in questions[]
      if (levelData.questions && Array.isArray(levelData.questions)) {
        for (const q of levelData.questions) {
          if (q.diagram) {
            const original = q.diagram;
            const updated = await uploadDiagramIfNeeded(q.diagram, weekData.weekId, level.id);
            if (original !== updated) {
              console.log(`✅ Uploaded diagram for ${level.id}: ${original} → ${updated}`);
            }
            q.diagram = updated;
          }
        }
      }

      const levelRef = weekRef.collection("Levels").doc(level.id);
      await levelRef.set(levelData);
    }

  } catch (error) {
    console.error("❌ Upload failed:", error);
  }
};

const setupLevels = async () => {
  const modulesPath = path.join(__dirname, "modules");
  const moduleNames = fs.readdirSync(modulesPath).filter(f => fs.statSync(path.join(modulesPath, f)).isDirectory());

  for (const moduleName of moduleNames) {
    const modulePath = path.join(modulesPath, moduleName);
    const weekFolders = fs.readdirSync(modulePath).filter(f => fs.statSync(path.join(modulePath, f)).isDirectory());

    for (const weekFolder of weekFolders) {
      console.log(`⏳ Setting up levels for ${moduleName} / ${weekFolder}...`);

      const weekData = loadWeekData(moduleName, weekFolder);
      if (!weekData) continue;

      await deleteExistingWeekData(weekData.weekId);
      await uploadWeekAndLevels(moduleName, weekFolder, weekData);

      console.log(`✅ Setup complete for ${moduleName} / ${weekFolder}`);
    }
  }
};

setupLevels();