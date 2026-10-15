/**
 * Placement des nœuds du graphe : des forces simples (les nœuds se repoussent, les liens
 * les rapprochent), calculées une fois, sans animation. Même entrée, même dessin.
 */

export interface Point {
  x: number;
  y: number;
}

interface Node {
  id: number;
  fixed: boolean;
}

interface Link {
  source_id: number;
  target_id: number;
}

export function layoutGraph(
  nodes: Node[],
  links: Link[],
  width: number,
  height: number,
  iterations = 220,
): Map<number, Point> {
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.38;
  const count = nodes.length;
  // Départ sur un cercle, dans l'ordre : le résultat ne dépend d'aucun hasard.
  const xs = nodes.map((n, i) =>
    n.fixed ? cx : cx + radius * Math.cos((2 * Math.PI * i) / Math.max(count, 1)),
  );
  const ys = nodes.map((n, i) =>
    n.fixed ? cy : cy + radius * Math.sin((2 * Math.PI * i) / Math.max(count, 1)),
  );
  const index = new Map(nodes.map((n, i) => [n.id, i]));
  const pairs: [number, number][] = [];
  for (const link of links) {
    const a = index.get(link.source_id);
    const b = index.get(link.target_id);
    if (a !== undefined && b !== undefined && a !== b) pairs.push([a, b]);
  }

  if (count >= 2) {
    const k = Math.sqrt((width * height) / count) * 0.75;
    const margin = 48;
    let temperature = width / 8;
    for (let step = 0; step < iterations; step += 1) {
      const dxs = new Array<number>(count).fill(0);
      const dys = new Array<number>(count).fill(0);
      for (let i = 0; i < count; i += 1) {
        for (let j = i + 1; j < count; j += 1) {
          let dx = (xs[i] ?? 0) - (xs[j] ?? 0);
          let dy = (ys[i] ?? 0) - (ys[j] ?? 0);
          let distance = Math.hypot(dx, dy);
          if (distance < 0.01) {
            dx = 0.01 * (i + 1);
            dy = 0.01 * (j + 1);
            distance = Math.hypot(dx, dy);
          }
          const force = (k * k) / distance;
          const fx = (dx / distance) * force;
          const fy = (dy / distance) * force;
          dxs[i] = (dxs[i] ?? 0) + fx;
          dys[i] = (dys[i] ?? 0) + fy;
          dxs[j] = (dxs[j] ?? 0) - fx;
          dys[j] = (dys[j] ?? 0) - fy;
        }
      }
      for (const [a, b] of pairs) {
        const dx = (xs[a] ?? 0) - (xs[b] ?? 0);
        const dy = (ys[a] ?? 0) - (ys[b] ?? 0);
        const distance = Math.max(Math.hypot(dx, dy), 0.01);
        const force = (distance * distance) / k;
        const fx = (dx / distance) * force;
        const fy = (dy / distance) * force;
        dxs[a] = (dxs[a] ?? 0) - fx;
        dys[a] = (dys[a] ?? 0) - fy;
        dxs[b] = (dxs[b] ?? 0) + fx;
        dys[b] = (dys[b] ?? 0) + fy;
      }
      for (let i = 0; i < count; i += 1) {
        if (nodes[i]?.fixed) continue;
        const x = xs[i] ?? cx;
        const y = ys[i] ?? cy;
        // Une légère attraction vers le centre garde les îlots dans le cadre.
        const mx = (dxs[i] ?? 0) + (cx - x) * 0.02 * k;
        const my = (dys[i] ?? 0) + (cy - y) * 0.02 * k;
        const length = Math.max(Math.hypot(mx, my), 0.01);
        const limited = Math.min(length, temperature);
        xs[i] = Math.min(width - margin, Math.max(margin, x + (mx / length) * limited));
        ys[i] = Math.min(height - margin, Math.max(margin, y + (my / length) * limited));
      }
      temperature *= 0.97;
    }
  }
  return new Map(nodes.map((n, i) => [n.id, { x: xs[i] ?? cx, y: ys[i] ?? cy }]));
}
