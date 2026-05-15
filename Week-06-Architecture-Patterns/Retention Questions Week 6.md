# Week 6 Retention Questions

## Rapid fire

```text
1. Why is Kafka not a normal queue?
2. What is the difference between an event and a command?
3. Why do consumers need idempotency?
4. What does consumer lag measure?
5. Why can adding consumers fail to fix lag?
6. What is a saga compensation?
7. Why is timeout ambiguity dangerous in payment systems?
8. What is retry amplification?
9. Why do circuit breakers need half-open state?
10. What problem does the outbox pattern solve?
```

## Compound scenario

```text
Checkout writes orders successfully. Payment provider times out. Inventory is
reserved. Kafka lag grows on one partition. Search is stale. Email confirmations
are delayed. Customer support sees payment authorizations with no visible order
confirmation.
```

Questions:

```text
1. Which state is authoritative?
2. Which symptoms are critical and which are freshness delays?
3. What should be synchronous?
4. What should be asynchronous?
5. Which idempotency keys are required?
6. Where can retries amplify the incident?
7. What should be communicated to support?
```
