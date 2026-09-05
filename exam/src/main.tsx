import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./styles.css";
import { CodeLogin } from "./pages/CodeLogin";
import { Paper } from "./pages/Paper";

createRoot(document.getElementById("root")!).render(
  <BrowserRouter>
    <Routes>
      <Route path="/" element={<CodeLogin />} />
      <Route path="/exam" element={<Paper />} />
    </Routes>
  </BrowserRouter>,
);
