import { AgentPreview } from "./agents/AgentPreview";
import { ThemeProvider } from "./core/theme/ThemeProvider";

const App: React.FC = () => {
  // State to store the agent details
  const agentDetails ={
      id: "qarar-ai",
      object: "qarar-ai",
      created_at: Date.now(),
      name: "QARAR AI",
      description: "Market & Decision Intelligence",
      model: "default",
      metadata: {
        logo: "qarar-ai-brandmark.png",
      },
  };

  return (
    <ThemeProvider>
      <div className="app-container">
        <AgentPreview
          resourceId="sample-resource-id"
          agentDetails={agentDetails}
        />
      </div>
    </ThemeProvider>
  );
};

export default App;
