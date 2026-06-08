import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createBrowserRouter, Navigate } from "react-router-dom";
import App from "@/App";
import Submit from "@/routes/Submit";
import Checkpoint from "@/routes/Checkpoint";
import Status from "@/routes/Status";
import Result from "@/routes/Result";
import History from "@/routes/History";
import "@/index.css";

const queryClient = new QueryClient();

const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <Navigate to="/submit" replace /> },
      { path: "submit", element: <Submit /> },
      { path: "checkpoint/:projectId", element: <Checkpoint /> },
      { path: "status/:projectId", element: <Status /> },
      { path: "result/:projectId", element: <Result /> },
      { path: "history", element: <History /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>,
);
