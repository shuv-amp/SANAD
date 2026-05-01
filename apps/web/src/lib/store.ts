import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

type SanadState = {
  documentId: string | null;
  setDocumentId: (documentId: string | null) => void;
};

export const useSanadStore = create<SanadState>()(
  persist(
    (set) => ({
      documentId: null,
      setDocumentId: (documentId) => set({ documentId })
    }),
    {
      name: "sanad-review-session",
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({ documentId: state.documentId })
    }
  )
);
