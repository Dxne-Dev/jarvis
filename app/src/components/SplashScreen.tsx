import { useEffect, useRef, useState } from "react";
import styles from "./SplashScreen.module.css";

interface Particle {
  x: number;
  y: number;
  tx: number;
  ty: number;
  vx: number;
  vy: number;
  size: number;
  color: string;
  alpha: number;
}

export function SplashScreen({ onComplete }: { onComplete?: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [closing, setClosing] = useState(false);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId = 0;
    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    const onResize = () => {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    };
    window.addEventListener("resize", onResize);

    // 1. Échantillonner les pixels du texte O-JARVIS
    const textCanvas = document.createElement("canvas");
    textCanvas.width = width;
    textCanvas.height = height;
    const tCtx = textCanvas.getContext("2d");
    const targets: { x: number; y: number }[] = [];

    if (tCtx) {
      const fontSize = Math.min(width * 0.13, 110);
      tCtx.font = `900 ${fontSize}px "Space Grotesk", sans-serif`;
      tCtx.fillStyle = "#ffffff";
      tCtx.textAlign = "center";
      tCtx.textBaseline = "middle";
      tCtx.fillText("O-JARVIS", width / 2, height / 2 - 20);

      const imgData = tCtx.getImageData(0, 0, width, height);
      const step = Math.max(3, Math.floor(width / 320)); // densité de particules

      for (let y = 0; y < height; y += step) {
        for (let x = 0; x < width; x += step) {
          const idx = (y * width + x) * 4;
          if ((imgData.data[idx + 3] ?? 0) > 128) {
            targets.push({ x, y });
          }
        }
      }
    }

    // 2. Générer les particules
    const colors = ["#00f0ff", "#00ff88", "#38bdf8", "#ffffff"];
    const particles: Particle[] = targets.map((t) => {
      // Départ aléatoire dispersé
      const angle = Math.random() * Math.PI * 2;
      const dist = Math.random() * Math.max(width, height) * 0.7 + 100;
      return {
        x: width / 2 + Math.cos(angle) * dist,
        y: height / 2 + Math.sin(angle) * dist,
        tx: t.x,
        ty: t.y,
        vx: 0,
        vy: 0,
        size: Math.random() * 1.8 + 1,
        color: colors[Math.floor(Math.random() * colors.length)] ?? "#00f0ff",
        alpha: Math.random() * 0.7 + 0.3,
      };
    });

    const startTime = performance.now();
    // Durée totale augmentée pour apprécier la formation et la contemplation
    const duration = 4500; // ms

    const render = (now: number) => {
      const elapsed = now - startTime;
      const p = Math.min(1, elapsed / duration);
      setProgress(Math.round(p * 100));

      ctx.fillStyle = "rgba(8, 12, 16, 0.22)";
      ctx.fillRect(0, 0, width, height);

      // Phase 1 (0 -> 60% du temps) : Convergence progressive vers les lettres
      // Phase 2 (60% -> 90%) : Stabilisation & micro-respiration
      // Phase 3 (90% -> 100%) : Dispersion légère vers l'avant
      const isStabilized = p > 0.55 && p <= 0.88;
      const isDispersing = p > 0.88;
      const breath = isStabilized ? Math.sin((elapsed - duration * 0.55) * 0.005) * 0.5 : 0;

      for (const pt of particles) {
        if (!isDispersing) {
          const dx = pt.tx - pt.x;
          const dy = pt.ty - pt.y;

          // Force d'attraction plus douce et cinématographique
          const ease = Math.min(0.045, 0.008 + p * 0.04);
          pt.vx += dx * ease;
          pt.vy += dy * ease;
          pt.vx *= 0.86;
          pt.vy *= 0.86;

          pt.x += pt.vx;
          pt.y += pt.vy;
        } else {
          // Éclatement fluide vers l'extérieur à la fin
          const angle = Math.atan2(pt.y - height / 2, pt.x - width / 2);
          pt.x += Math.cos(angle) * (pt.size * 3.5);
          pt.y += Math.sin(angle) * (pt.size * 3.5);
          pt.alpha *= 0.94;
        }

        ctx.fillStyle = pt.color;
        ctx.globalAlpha = Math.max(0, pt.alpha);
        ctx.beginPath();
        ctx.arc(pt.x, pt.y, Math.max(0.5, pt.size + breath), 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;

      if (elapsed < duration) {
        animId = requestAnimationFrame(render);
      } else {
        // Fin de l'animation -> fermeture propre
        setClosing(true);
        setTimeout(() => {
          onComplete?.();
        }, 800);
      }
    };

    animId = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener("resize", onResize);
    };
  }, [onComplete]);

  return (
    <div
      className={styles.splash}
      data-closing={closing}
      role="status"
      aria-label="Chargement d'O-jarvis"
    >
      <canvas ref={canvasRef} className={styles.canvas} />
      <div className={styles.meta}>
        <span className={styles.status}>[ SYSTEM INITIALIZING ]</span>
        <div className={styles.progressBar}>
          <div className={styles.progressFill} style={{ width: `${progress}%` }} />
        </div>
      </div>
    </div>
  );
}
