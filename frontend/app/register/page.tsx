"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AuthForm } from "@/components/AuthForm";
import { registerUser } from "@/lib/api";
import { saveToken } from "@/lib/auth";

export default function RegisterPage() {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  async function handleSubmit(email: string, password: string) {
    setError(null);
    setLoading(true);
    try {
      const token = await registerUser(email, password);
      saveToken(token);
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro desconhecido");
    } finally {
      setLoading(false);
    }
  }

  return <AuthForm mode="register" onSubmit={handleSubmit} error={error} loading={loading} />;
}
