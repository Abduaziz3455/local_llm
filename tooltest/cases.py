"""
Test cases for poll tool-calling evaluation.

Each case:
  id        : short identifier
  lang      : 'en' | 'uz'
  msg       : the user's message
  expect    : 'create_poll' | 'edit_poll' | None  (None = general question,
              the model should NOT call any tool and just answer in text)
  check     : optional dict of expected argument values for a stronger check:
                question_kw  -> substrings expected (any one) in question
                n_options    -> exact number of options expected
                options_kw   -> substrings each expected somewhere in options
                multiple     -> expected allows_multiple_answers (bool)
                anonymous    -> expected is_anonymous (bool)
                type         -> 'quiz' | 'regular'
                correct      -> expected correct_option_id (int)
                action       -> expected edit_poll action
"""

CASES = [
    # ---------------- English: should CREATE a poll ----------------
    dict(id="en_simple", lang="en",
         msg="Create a poll: What's your favorite programming language? Options: Python, Go, Rust, JavaScript.",
         expect="create_poll",
         check=dict(n_options=4, options_kw=["Python", "Go", "Rust", "JavaScript"])),

    dict(id="en_anon", lang="en",
         msg="Make an anonymous poll asking if people will join tomorrow's meeting. Yes or No.",
         expect="create_poll",
         check=dict(n_options=2, anonymous=True)),

    dict(id="en_multi", lang="en",
         msg="Start a poll where people can pick several fruits they like: apple, banana, grape, peach. Multiple answers allowed.",
         expect="create_poll",
         check=dict(n_options=4, multiple=True)),

    dict(id="en_quiz", lang="en",
         msg="Create a quiz: What is the capital of Uzbekistan? Tashkent, Samarkand, Bukhara. The correct answer is Tashkent.",
         expect="create_poll",
         check=dict(n_options=3, type="quiz", correct=0)),

    dict(id="en_no_options", lang="en",
         msg="Set up a poll asking the team which day works best for the standup.",
         expect="create_poll"),

    # ---------------- English: should EDIT a poll ----------------
    dict(id="en_edit_add", lang="en",
         msg="Add another option 'Maybe' to the last poll.",
         expect="edit_poll",
         check=dict(action="add_option")),

    dict(id="en_edit_close", lang="en",
         msg="Close the current poll, voting is over.",
         expect="edit_poll",
         check=dict(action="close")),

    # ---------------- English: GENERAL (no tool) ----------------
    dict(id="en_gen_capital", lang="en",
         msg="What is the capital of Uzbekistan?",
         expect=None),

    dict(id="en_gen_chat", lang="en",
         msg="Hi! Can you explain what a poll is in one sentence?",
         expect=None),

    dict(id="en_gen_code", lang="en",
         msg="How do I sort a list of numbers in Python?",
         expect=None),

    # ---------------- Uzbek: should CREATE a poll ----------------
    dict(id="uz_simple", lang="uz",
         msg="So'rovnoma yarating: Sevimli rangingiz qaysi? Variantlar: qizil, ko'k, yashil, sariq.",
         expect="create_poll",
         check=dict(n_options=4, options_kw=["qizil", "yashil"])),

    dict(id="uz_anon", lang="uz",
         msg="Anonim so'rovnoma yarat: ertaga uchrashuvga kelasizmi? Ha yoki Yo'q.",
         expect="create_poll",
         check=dict(n_options=2, anonymous=True)),

    dict(id="uz_multi", lang="uz",
         msg="Bir nechta javob tanlash mumkin bo'lgan so'rovnoma yarat: qaysi mevalarni yoqtirasiz? olma, banan, uzum, shaftoli.",
         expect="create_poll",
         check=dict(n_options=4, multiple=True)),

    dict(id="uz_quiz", lang="uz",
         msg="Test savol yarat: O'zbekiston poytaxti qaysi shahar? Toshkent, Samarqand, Buxoro. To'g'ri javob Toshkent.",
         expect="create_poll",
         check=dict(n_options=3, type="quiz", correct=0)),

    dict(id="uz_meeting", lang="uz",
         msg="Jamoa uchun so'rovnoma tashkil qil: dushanba yig'ilishi soat nechada bo'lsin? 9:00, 10:00, 11:00.",
         expect="create_poll",
         check=dict(n_options=3)),

    dict(id="uz_food", lang="uz",
         msg="Tushlik uchun ovoz berish so'rovnomasini boshlang: osh, lag'mon, manti, somsa.",
         expect="create_poll",
         check=dict(n_options=4, options_kw=["osh", "somsa"])),

    # ---------------- Uzbek: should EDIT a poll ----------------
    dict(id="uz_edit_add", lang="uz",
         msg="Oldingi so'rovnomaga yana bitta variant qo'sh: 'Bilmayman'.",
         expect="edit_poll",
         check=dict(action="add_option")),

    dict(id="uz_edit_close", lang="uz",
         msg="So'rovnomani yoping, ovoz berish tugadi.",
         expect="edit_poll",
         check=dict(action="close")),

    # ---------------- Uzbek: GENERAL (no tool) ----------------
    dict(id="uz_gen_capital", lang="uz",
         msg="O'zbekiston poytaxti qaysi shahar?",
         expect=None),

    dict(id="uz_gen_weather", lang="uz",
         msg="Salom! Bugun kayfiyating qanday?",
         expect=None),

    dict(id="uz_gen_explain", lang="uz",
         msg="So'rovnoma nima ekanligini bir gapda tushuntirib bera olasanmi?",
         expect=None),

    dict(id="uz_gen_recipe", lang="uz",
         msg="Oshni qanday tayyorlanadi, qisqacha ayt.",
         expect=None),
]
