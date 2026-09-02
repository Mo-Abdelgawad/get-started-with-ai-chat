import { Button, Spinner } from "@fluentui/react-components";
import { bundleIcon, DeleteFilled, DeleteRegular } from "@fluentui/react-icons";
import { CopilotMessageV2 as CopilotMessage } from "@fluentui-copilot/react-copilot-chat";
import {
  ReferenceListV2 as ReferenceList,
  ReferenceOverflowButton,
} from "@fluentui-copilot/react-reference";
import { Suspense } from "react";

import { Markdown } from "../core/Markdown";
import { UsageInfo } from "./UsageInfo";
import { IAssistantMessageProps } from "./chatbot/types";

import styles from "./AgentPreviewChatBot.module.css";
import { AgentIcon } from "./AgentIcon";

const DeleteIcon = bundleIcon(DeleteFilled, DeleteRegular);

export function AssistantMessage({
  message,
  loadingState,
  agentName,
  showUsageInfo,
  onDelete,
}: IAssistantMessageProps): React.JSX.Element {
  const hasAnnotations = message.annotations && message.annotations.length > 0;
  const references = hasAnnotations
    ? message.annotations?.map((annotation, index) => (
        <div key={index} className={styles.referenceItem}>
          {annotation.text || annotation.file_name}
        </div>
      ))
    : [];

  return (
    <CopilotMessage
      id={"msg-" + message.id}
      key={message.id}
      actions={
        <span>
          {onDelete && message.usageInfo && (
            <Button
              appearance="subtle"
              icon={<DeleteIcon />}
              onClick={() => {
                void onDelete(message.id);
              }}
            />
          )}
        </span>
      }
      avatar={<AgentIcon alt="" iconName="qarar-ai-brandmark.png" />}
      className={styles.copilotChatMessage}
      disclaimer={<span>Market & Decision Intelligence</span>}
      style={{ fontFamily: "'Montserrat', 'Segoe UI', sans-serif" }}
      footnote={
        <>
          {hasAnnotations && (
            <div className={styles.referenceListRoot}>
              <ReferenceList
                className={styles.referenceList}
                maxVisibleReferences={3}
                minVisibleReferences={2}
                showLessButton={
                  <ReferenceOverflowButton>Show Less</ReferenceOverflowButton>
                }
                showMoreButton={
                  <ReferenceOverflowButton
                    text={(overflowCount) => `+${overflowCount.toString()}`}
                  />
                }
              >
                {references}
              </ReferenceList>
            </div>
          )}
          {showUsageInfo && message.usageInfo && (
            <UsageInfo info={message.usageInfo} duration={message.duration} />
          )}
        </>
      }
      loadingState={loadingState}
      name={<span className={styles.assistantName}>{agentName ?? "QARAR AI"}</span>}
    >
      <Suspense fallback={<Spinner size="small" />}>
        <Markdown content={message.content} />
      </Suspense>
    </CopilotMessage>
  );
}
