import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";

const FloatingButton = ({ children, onClick, isComingSoon = false }) => {
  const [floating, setFloating] = useState({ x: 0, y: 0 });
  const [showText, setShowText] = useState(false);

  useEffect(() => {
    const delay = Math.random() * 1000; // Each button starts at a different time
    setTimeout(() => {
      const interval = setInterval(() => {
        setFloating({
          x: (Math.random() * 6 - 3), // Smaller movement range (-3 to +3)
          y: (Math.random() * 6 - 3),
        });
      }, 5000); // Slower movement interval (5s)

      return () => clearInterval(interval);
    }, delay);
  }, []); // Runs only once when the component mounts

  return (
    <div className="shimmer-container" style={{ position: "relative" }}>
      <motion.button
        className="floating-button"
        onClick={() => {
          if (isComingSoon) {
            console.log("Showing text!"); // Check if this appears in console
            setShowText(true);
            setTimeout(() => setShowText(false), 1200);
          } else {
            onClick && onClick();
          }
        }}
        initial={{ scale: 1, opacity: 1 }}
        animate={{
          x: floating.x,
          y: floating.y,
        }}
        transition={{
          x: { duration: 4, ease: "easeInOut", repeat: Infinity, repeatType: "mirror" }, // Slower motion
          y: { duration: 4, ease: "easeInOut", repeat: Infinity, repeatType: "mirror" }
        }}
        whileTap={{ scale: 0.75, opacity: 0.6 }}
        whileHover={{ scale: 1.05 }}
      >
        {children}
      </motion.button>

      {/* AnimatePresence ensures smooth fade-in/out of the text */}
      <AnimatePresence>
        {showText && (
          <motion.div
            className="coming-soon-text"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: -10 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 1 }}
            style={{
              position: "absolute",
              top: "-42px",
              left: "30%",
              transform: "translateX(-50%)",
              whiteSpace: "nowrap",
              zIndex: 1000, // ✅ Ensures text appears on top
            }}
          >
            Coming Soon...
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default FloatingButton;
