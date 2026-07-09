import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createBrowserRouter, Navigate } from "react-router-dom";
import App from "@/App";
import Submit from "@/routes/Submit";
import Planning from "@/routes/Planning";
import Checkpoint from "@/routes/Checkpoint";
import Status from "@/routes/Status";
import Result from "@/routes/Result";
import History from "@/routes/History";
import Login from "@/routes/Login";
import Register from "@/routes/Register";
import { AuthProvider } from "@/auth/AuthContext";
import ProtectedRoute from "@/auth/ProtectedRoute";
import "@/index.css";

const queryClient = new QueryClient();

const router = createBrowserRouter([
  // Public auth routes (outside the protected shell).
  { path: "/login", element: <Login /> },
  { path: "/register", element: <Register /> },
  // Everything else requires a session: ProtectedRoute gates the App shell.
  {
    element: <ProtectedRoute />,
    children: [
      {
        path: "/",
        element: <App />,
        children: [
          { index: true, element: <Navigate to="/submit" replace /> },
          { path: "submit", element: <Submit /> },
          { path: "planning/:jobId", element: <Planning /> },
          { path: "checkpoint/:projectId", element: <Checkpoint /> },
          { path: "status/:projectId", element: <Status /> },
          { path: "result/:projectId", element: <Result /> },
          { path: "history", element: <History /> },
        ],
      },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
