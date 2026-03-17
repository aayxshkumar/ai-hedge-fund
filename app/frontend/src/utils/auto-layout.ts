import Dagre from '@dagrejs/dagre';
import type { Edge, Node } from '@xyflow/react';

const NODE_WIDTH = 260;
const NODE_HEIGHT = 180;
const RANK_SEP = 120;
const NODE_SEP = 60;

export function getLayoutedElements(
  nodes: Node[],
  edges: Edge[],
  direction: 'LR' | 'TB' = 'LR',
): { nodes: Node[]; edges: Edge[] } {
  const g = new Dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir: direction,
    ranksep: RANK_SEP,
    nodesep: NODE_SEP,
    marginx: 40,
    marginy: 40,
  });

  for (const node of nodes) {
    g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  Dagre.layout(g);

  const layoutedNodes = nodes.map((node) => {
    const pos = g.node(node.id);
    return {
      ...node,
      position: {
        x: pos.x - NODE_WIDTH / 2,
        y: pos.y - NODE_HEIGHT / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
}

/**
 * Check if a bounding box overlaps with any existing node.
 * Returns the required Y offset to avoid overlap, or 0 if no overlap.
 */
export function findNonOverlappingPosition(
  existingNodes: Node[],
  newBounds: { minX: number; minY: number; maxX: number; maxY: number },
  gap = 80,
): { dx: number; dy: number } {
  if (existingNodes.length === 0) return { dx: 0, dy: 0 };

  const existingBounds = existingNodes.map((n) => ({
    minX: n.position.x,
    minY: n.position.y,
    maxX: n.position.x + NODE_WIDTH,
    maxY: n.position.y + NODE_HEIGHT,
  }));

  let dy = 0;
  let attempts = 0;
  const maxAttempts = 50;

  while (attempts < maxAttempts) {
    const shifted = {
      minX: newBounds.minX,
      minY: newBounds.minY + dy,
      maxX: newBounds.maxX,
      maxY: newBounds.maxY + dy,
    };

    const hasOverlap = existingBounds.some(
      (eb) =>
        shifted.minX < eb.maxX + gap &&
        shifted.maxX > eb.minX - gap &&
        shifted.minY < eb.maxY + gap &&
        shifted.maxY > eb.minY - gap,
    );

    if (!hasOverlap) return { dx: 0, dy };

    dy += NODE_HEIGHT + gap;
    attempts++;
  }

  return { dx: 0, dy };
}
