import type { ReactNode } from "react";
import { motion } from "framer-motion";

interface AnimatedListProps<T> {
  items: T[];
  getKey: (item: T) => string;
  renderItem: (item: T) => ReactNode;
  className?: string;
}

const containerVariants = {
  hidden: {},
  visible: {
    transition: {
      staggerChildren: 0.045,
      delayChildren: 0.02,
    },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 10, scale: 0.985 },
  visible: { opacity: 1, y: 0, scale: 1 },
};

export function AnimatedList<T>({ items, getKey, renderItem, className }: AnimatedListProps<T>) {
  const remountKey = items.map((item) => getKey(item)).join("|");
  return (
    <motion.ul
      key={remountKey}
      className={className}
      variants={containerVariants}
      initial="hidden"
      animate="visible"
    >
      {items.map((item) => (
        <motion.li key={getKey(item)} variants={itemVariants}>
          {renderItem(item)}
        </motion.li>
      ))}
    </motion.ul>
  );
}
