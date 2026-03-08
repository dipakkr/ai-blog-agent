"use client";

import { FaqItem } from "@/lib/api";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

interface FaqTabProps {
  faq: FaqItem[];
}

export function FaqTab({ faq }: FaqTabProps) {
  if (faq.length === 0) {
    return <p className="text-sm text-muted-foreground">No FAQ items generated.</p>;
  }

  return (
    <div className="space-y-2">
      <h3 className="font-semibold mb-3">
        Frequently Asked Questions{" "}
        <span className="text-muted-foreground font-normal text-sm">({faq.length})</span>
      </h3>
      <Accordion className="space-y-2">
        {faq.map((item, idx) => (
          <AccordionItem
            key={idx}
            value={`faq-${idx}`}
            className="border rounded-lg px-4"
          >
            <AccordionTrigger className="text-sm font-medium text-left hover:no-underline py-3">
              {item.question}
            </AccordionTrigger>
            <AccordionContent className="text-sm text-muted-foreground pb-3 leading-relaxed">
              {item.answer}
            </AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>
    </div>
  );
}
