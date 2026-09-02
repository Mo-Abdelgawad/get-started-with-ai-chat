import type { ReactNode } from "react";

import styles from "./AgentIcon.module.css";

export interface IAgentIconProps {
  /**
   * The name of the icon to display
   */
  iconName?: string;
  /**
   * Alt text for the icon
   * This is used for accessibility and SEO purposes
   * and should describe the icon's purpose or meaning.
   * If the icon is purely decorative, a blank string can be used.
   */
  alt: string;
  /**
   * Optional class name for the icon
   */
  iconClassName?: string;
}

export function AgentIcon({
  iconName = "qarar-ai-brandmark.png",
  iconClassName,
  alt = "QARAR AI logo",
}: IAgentIconProps): ReactNode {
  return (
    <div className={styles.iconContainer}>
      <img
        alt={alt}
        className={iconClassName ?? styles.icon}
        src={iconName.startsWith("/") || iconName.startsWith("http") ? iconName : `/static/assets/${iconName}`}
      />
    </div>
  );
}
